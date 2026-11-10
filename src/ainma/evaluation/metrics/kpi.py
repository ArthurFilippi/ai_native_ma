"""KPI extraction (eval plan section 7)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ainma.evaluation.metrics.common import ratio, share
from ainma.evaluation.metrics.numbers import close, value_in_text_any_scale

REL_TOLERANCE = 0.005


@dataclass(frozen=True)
class KpiOutcome:
    """One truth table cell. `value` is `None` when the system returned nothing.
    `quote_valid` is `None` unless the value was sourced (computed values have no quote)."""

    truth: float
    value: float | None
    quote_valid: bool | None = None


@dataclass(frozen=True)
class KpiScores:
    accuracy: float | None  # correct / all truth cells (a missing value is not correct)
    wrong_value_rate: float | None  # wrong non missing / non missing: the dangerous error
    missing_rate: float | None  # the safe error
    citation_validity: float | None


def within_tolerance(value: float, truth: float, rel_tol: float = REL_TOLERANCE) -> bool:
    if truth == 0:
        return abs(value) <= 1e-9
    return close(value, truth, rel_tol)


def quote_contains_value(quote: str, value: float) -> bool:
    """The cited quote contains the value, up to a power of 1000 and the 0.5 percent tolerance."""
    return value_in_text_any_scale(value, quote)


def kpi_scores(outcomes: Sequence[KpiOutcome], rel_tol: float = REL_TOLERANCE) -> KpiScores:
    answered = [o for o in outcomes if o.value is not None]
    correct = sum(
        1 for o in answered if o.value is not None and within_tolerance(o.value, o.truth, rel_tol)
    )
    return KpiScores(
        accuracy=ratio(correct, len(outcomes)),
        wrong_value_rate=ratio(len(answered) - correct, len(answered)),
        missing_rate=ratio(len(outcomes) - len(answered), len(outcomes)),
        citation_validity=share([o.quote_valid for o in outcomes if o.quote_valid is not None]),
    )
