"""Refine a screening request from a sentence (D98).

`refine_request` sends the analyst's sentence and the current request to the `refine_screening`
task; the result is a typed change (filters to set, weights to raise or lower), never a query. The
mock routine reads common wordings (buyer types, regions of the buyer universe, size bounds,
emphasis on a criterion); a live model gets the same request and returns the same schema. Code
merges the change into the request and lists what it understood, so the analyst can remove it.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ainma.contracts import BuyerType, ScreeningRequest, Strict
from ainma.llm.base import LLM
from ainma.llm.tasks import TASK_REFINE_SCREENING
from ainma.screening.criteria import build_criteria


class Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RefineRequest(Strict):
    text: str
    geographies: list[str]  # regions the buyer universe uses
    criteria: dict[str, str]  # criterion key -> label


class RefineChange(Lenient):
    buyer_types: list[Literal["strategic", "financial"]] = Field(default_factory=list)
    geographies: list[str] = Field(default_factory=list)
    min_size_eur_m: float | None = None
    max_size_eur_m: float | None = None
    emphasis: dict[str, float] = Field(default_factory=dict)  # criterion key -> weight factor
    understood: list[str] = Field(default_factory=list)  # short phrases shown as chips


class RefineOutcome(Strict):
    request: ScreeningRequest
    understood: list[str]


REFINE_PROMPT = """You turn a banker's sentence about the buyers they want into a typed change of
a screening request. Use only the listed regions and criteria keys. Set a size bound only when the
sentence gives a number (EUR million). Emphasis multiplies a criterion weight: 2 for "prefer",
"focus on", 0 for "ignore". List each understood item as a short phrase. Return JSON only."""

_TYPES: tuple[tuple[re.Pattern[str], BuyerType], ...] = (
    (
        re.compile(r"\b(financial|sponsors?|private equity|pe funds?|funds?)\b", re.I),
        BuyerType.FINANCIAL,
    ),
    (re.compile(r"\b(strategic|strategics|corporates?|industrials?)\b", re.I), BuyerType.STRATEGIC),
)
_AMOUNT = r"(?:eur|€)?\s*([\d.,]+)\s*(bn|billion|m|million)?"
_MIN = re.compile(
    rf"\b(?:above|over|more than|at least|min(?:imum)?|bigger than|larger than)\s+{_AMOUNT}", re.I
)
_MAX = re.compile(
    rf"\b(?:below|under|less than|at most|max(?:imum)?|smaller than)\s+{_AMOUNT}", re.I
)
_EMPHASIS: tuple[tuple[re.Pattern[str], str, float, str], ...] = (
    (
        re.compile(
            r"recent (?:acquisitions|deals|acquirers)|active (?:acquirers|buyers)|acquisitive", re.I
        ),
        "recent_activity",
        2.0,
        "prefer recent acquirers",
    ),
    (
        re.compile(r"antitrust|competition (?:risk|issues)|merger control", re.I),
        "antitrust",
        2.0,
        "weigh antitrust risk",
    ),
    (
        re.compile(r"\bfdi\b|foreign investment|regulatory (?:risk|approval)", re.I),
        "regulatory_fdi",
        2.0,
        "weigh FDI and regulatory risk",
    ),
    (re.compile(r"ticket|cheque size|equity size", re.I), "ticket_fit", 2.0, "weigh ticket fit"),
    (
        re.compile(r"integration|bandwidth", re.I),
        "integration_bandwidth",
        2.0,
        "weigh integration bandwidth",
    ),
    (
        re.compile(r"dry powder|fund (?:life|cycle)|investment period", re.I),
        "fund_lifecycle",
        2.0,
        "weigh fund lifecycle",
    ),
)


def _eur_m(number: str, scale: str | None) -> float:
    value = float(number.replace(",", ""))
    return value * 1000.0 if scale and scale.lower() in ("bn", "billion") else value


def refine_rules(request: RefineRequest) -> RefineChange:
    text = request.text
    change = RefineChange()
    for pattern, buyer_type in _TYPES:
        if pattern.search(text):
            change.buyer_types.append(buyer_type.value)
            change.understood.append(f"type: {buyer_type.value}")
    for region in request.geographies:
        if re.search(rf"\b{re.escape(region)}\b", text, re.I):
            change.geographies.append(region)
            change.understood.append(f"region: {region}")
    if low := _MIN.search(text):
        change.min_size_eur_m = _eur_m(low.group(1), low.group(2))
        change.understood.append(f"size from EUR {change.min_size_eur_m:g}m")
    if high := _MAX.search(text):
        change.max_size_eur_m = _eur_m(high.group(1), high.group(2))
        change.understood.append(f"size to EUR {change.max_size_eur_m:g}m")
    for pattern, key, factor, label in _EMPHASIS:
        if key in request.criteria and pattern.search(text):
            change.emphasis[key] = factor
            change.understood.append(label)
    return change


def mock_refine(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    return refine_rules(RefineRequest.model_validate_json(user))


async def refine_request(
    text: str, current: ScreeningRequest, *, geographies: list[str], llm: LLM
) -> RefineOutcome:
    criteria = build_criteria(current.weights)
    request = RefineRequest(
        text=text,
        geographies=sorted(set(geographies)),
        criteria={c.key: c.label for c in criteria},
    )
    change, _ = await llm.complete_json(
        task=TASK_REFINE_SCREENING,
        system=REFINE_PROMPT,
        user=request.model_dump_json(),
        schema=RefineChange,
        stage="screening",
    )
    filters = current.filters.model_copy()
    known_regions = set(request.geographies)
    if change.buyer_types:
        filters.buyer_types = sorted({BuyerType(t) for t in change.buyer_types}, key=str)
    regions = [g for g in change.geographies if g in known_regions]
    if regions:
        filters.geographies = sorted(set(filters.geographies) | set(regions))
    if change.min_size_eur_m is not None:
        filters.min_size_eur_m = change.min_size_eur_m
    if change.max_size_eur_m is not None:
        filters.max_size_eur_m = change.max_size_eur_m
    weights = dict(current.weights)
    defaults = {c.key: c.weight for c in criteria}
    for key, factor in change.emphasis.items():
        if key in defaults and 0.0 <= factor <= 10.0:
            weights[key] = weights.get(key, defaults[key]) * factor
    return RefineOutcome(
        request=current.model_copy(update={"filters": filters, "weights": weights}),
        understood=change.understood,
    )
