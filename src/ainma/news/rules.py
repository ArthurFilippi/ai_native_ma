"""Rule routine behind the mock provider for `extract_events` (deterministic, offline).

It reads the headline patterns of the synthetic feed. It is a baseline, not a model: a live model
gets the same request and must generalise to other wordings.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from ainma.news.schemas import EventDraft, ExtractEventsRequest, ExtractEventsResult

_NAME = r"\b([A-Z][\w&-]*(?: [A-Z][\w&-]*)*)"
_Kind = Literal["acquisition", "leadership_change", "rumour", "price"]
_Stance = Literal["report", "denial", "correction"]
_PATTERNS: tuple[tuple[re.Pattern[str], _Kind, _Stance], ...] = (
    (
        re.compile(rf"Correction: price for {_NAME} and {_NAME} was EUR ([\d,.]+) million"),
        "price",
        "correction",
    ),
    (re.compile(rf"Price for {_NAME} and {_NAME} put at EUR ([\d,.]+) million"), "price", "report"),
    (re.compile(rf"{_NAME} completes acquisition of {_NAME}"), "acquisition", "report"),
    (
        re.compile(rf"(?:Trade wire|Market brief|Deal monitor): {_NAME} buys {_NAME}"),
        "acquisition",
        "report",
    ),
    (re.compile(rf"{_NAME} appoints {_NAME} as chief executive"), "leadership_change", "report"),
    (re.compile(rf"{_NAME} is said to weigh an offer for {_NAME}"), "rumour", "report"),
    (re.compile(rf"{_NAME} denies interest in {_NAME}"), "rumour", "denial"),
)


def _sentence(text: str, start: int, end: int) -> str:
    period = text.rfind(". ", 0, start)
    left = max(period + 2 if period >= 0 else 0, text.rfind("\n", 0, start) + 1)
    stops = [i for i in (text.find(".", end), text.find("\n", end)) if i >= 0]
    return text[left : min(stops) if stops else len(text)].strip()


def extract_events_rules(text: str) -> ExtractEventsResult:
    drafts: list[EventDraft] = []
    seen: set[tuple[str, str, str, str]] = set()
    for pattern, kind, stance in _PATTERNS:
        for match in pattern.finditer(text):
            actor, counterparty = match.group(1), match.group(2)
            key = (kind, stance, actor, counterparty)
            if key in seen:
                continue  # the headline and the body often repeat the same sentence
            seen.add(key)
            value = float(match.group(3).replace(",", "")) if kind == "price" else None
            drafts.append(
                EventDraft(
                    kind=kind,
                    stance=stance,
                    actor=actor,
                    counterparty=counterparty,
                    value_eur_m=value,
                    quote=_sentence(text, match.start(), match.end()),
                )
            )
    return ExtractEventsResult(events=drafts)


def mock_extract_events(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    request = ExtractEventsRequest.model_validate_json(user)
    return extract_events_rules(request.text)
