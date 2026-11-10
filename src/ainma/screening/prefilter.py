"""Stage 1: structured buyer fields against the request filters. No retrieval, no LLM."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from ainma.contracts import (
    BuyerProfile,
    CriterionResult,
    CriterionStatus,
    Deal,
    ScreeningFilters,
)
from ainma.screening.criteria import PREFILTER_KEYS, ScreeningParams

_MIN_STEM = 5
_STEM_LENGTH = 6


def _stems(sector: str) -> set[str]:
    words = re.findall(r"[a-z]+", sector.lower())
    return {w[:_STEM_LENGTH] for w in words if len(w) >= _MIN_STEM}


def sectors_overlap(buyer_sectors: Iterable[str], targets: Sequence[str]) -> list[str]:
    """Buyer sectors that match a target sector: same text, one containing the other, or at least
    half of the word stems in common (`industrial` and `industrials` share the stem `indust`)."""
    matched: list[str] = []
    for own in buyer_sectors:
        for target in targets:
            a, b = own.lower().strip(), target.lower().strip()
            sa, sb = _stems(a), _stems(b)
            shared = len(sa & sb)
            union = len(sa | sb)
            if a == b or a in b or b in a or (union and shared / union >= 0.5):
                matched.append(own)
                break
    return matched


def _result(key: str, status: CriterionStatus, rationale: str) -> CriterionResult:
    return CriterionResult(criterion_key=key, status=status, rationale=rationale)


def _not_requested(key: str, what: str) -> CriterionResult:
    return _result(
        key,
        CriterionStatus.UNKNOWN,
        f"No {what} in the request: not evaluated, and never assumed.",
    )


def prefill_from_deal(
    filters: ScreeningFilters, deal: Deal, params: ScreeningParams
) -> tuple[ScreeningFilters, dict[str, str]]:
    """The typed filters, completed by the deal's own facts where a filter is empty.

    Returns the effective filters and, per prefilter key that was prefilled, the sentence that
    says where the value comes from. A typed filter always wins over the deal.
    """
    update: dict[str, object] = {}
    origin: dict[str, str] = {}
    if not filters.buyer_types and deal.buyer_types:
        update["buyer_types"] = list(deal.buyer_types)
        origin["buyer_type"] = "Buyer types from the deal record."
    if not filters.geographies and deal.geographies:
        update["geographies"] = list(deal.geographies)
        origin["geography"] = f"Region from the deal record ({', '.join(deal.geographies)})."
    if filters.min_size_eur_m is None and filters.max_size_eur_m is None and deal.ev_eur_m:
        update["min_size_eur_m"] = deal.ev_eur_m * params.min_size_multiple_of_ev
        update["max_size_eur_m"] = deal.ev_eur_m * params.max_size_multiple_of_ev
        origin["size_range"] = (
            f"Size range from the deal value EUR {deal.ev_eur_m:g}m x "
            f"{params.min_size_multiple_of_ev:g} to {params.max_size_multiple_of_ev:g} "
            "(parameters, not sources)."
        )
    return filters.model_copy(update=update), origin


def prefilter_results(
    buyer: BuyerProfile,
    filters: ScreeningFilters,
    target_sectors: Sequence[str],
    prefilled: dict[str, str] | None = None,
) -> list[CriterionResult]:
    """One result per prefilter criterion, in the order of `PREFILTER_KEYS`. `prefilled` maps a
    key to the sentence saying that its filter came from the deal record."""
    results: dict[str, CriterionResult] = {}

    if filters.buyer_types:
        wanted = ", ".join(t.value for t in filters.buyer_types)
        ok = buyer.buyer_type in filters.buyer_types
        results["buyer_type"] = _result(
            "buyer_type",
            CriterionStatus.MET if ok else CriterionStatus.NOT_MET,
            f"Structured profile: {buyer.buyer_type.value} buyer; requested: {wanted}.",
        )
    else:
        results["buyer_type"] = _not_requested("buyer_type", "buyer type filter")

    matched = sectors_overlap(buyer.sectors, target_sectors)
    results["sector_focus"] = _result(
        "sector_focus",
        CriterionStatus.MET if matched else CriterionStatus.NOT_MET,
        (
            f"Structured profile sectors {', '.join(matched)} match the target "
            f"({', '.join(target_sectors)})."
            if matched
            else f"Structured profile sectors ({', '.join(buyer.sectors)}) do not match the "
            f"target ({', '.join(target_sectors)})."
        ),
    )

    if filters.geographies:
        own = {g.lower() for g in buyer.geographies}
        common = [g for g in filters.geographies if g.lower() in own]
        results["geography"] = _result(
            "geography",
            CriterionStatus.MET if common else CriterionStatus.NOT_MET,
            (
                f"Structured profile covers {', '.join(common)}."
                if common
                else f"Structured profile geographies ({', '.join(buyer.geographies)}) do not "
                f"include {', '.join(filters.geographies)}."
            ),
        )
    else:
        results["geography"] = _not_requested("geography", "geography filter")

    low, high = filters.min_size_eur_m, filters.max_size_eur_m
    if low is None and high is None:
        results["size_range"] = _not_requested("size_range", "size range")
    else:
        inside = (low is None or buyer.size_eur_m >= low) and (
            high is None or buyer.size_eur_m <= high
        )
        parts = [] if low is None else [f"from EUR {low:g}m"]
        parts += [] if high is None else [f"to EUR {high:g}m"]
        bounds = " ".join(parts)
        results["size_range"] = _result(
            "size_range",
            CriterionStatus.MET if inside else CriterionStatus.NOT_MET,
            f"Structured size EUR {buyer.size_eur_m:g}m, requested range {bounds}.",
        )
    for key, note in (prefilled or {}).items():
        if key in results:
            result = results[key]
            results[key] = result.model_copy(update={"rationale": f"{result.rationale} {note}"})
    return [results[key] for key in PREFILTER_KEYS]
