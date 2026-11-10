"""The criteria table (spec section 10) and the documented parameters behind the thresholds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from ainma.contracts import BuyerType, Criterion


@dataclass(frozen=True)
class ScreeningParams:
    """Every number the deep stage assumes, in one place. None of them comes from a source.

    - The indicative equity cheque is `EBITDA x ev_ebitda_multiple x equity_share_of_ev`, where
      EBITDA is the latest value extracted from the deal's own documents. The multiple and the
      equity share are placeholders to be set by the banker, not market data.
    - A strategic buyer's EV is approximated by its market capitalisation (`size_eur_m`).
    - `as_of` is the reference date of every recency rule. When `None`, the latest publication
      date visible in the deal scope is used, so runs on a fixed corpus stay reproducible.
    """

    ev_ebitda_multiple: float = 8.0
    equity_share_of_ev: float = 0.5
    ticket_not_met_below: float = 0.05
    ticket_not_met_above: float = 0.40
    ticket_healthy_low: float = 0.10
    ticket_healthy_high: float = 0.25
    ev_ratio_transformational: float = 0.40
    ev_ratio_not_met_above: float = 0.60
    min_investment_years_remaining: float = 2.0
    recent_activity_months: int = 36
    integration_window_months: int = 24
    max_recent_acquisitions: int = 2
    antitrust_combined_share_pct: float = 35.0
    as_of: date | None = None


PREFILTER_KEYS = ("buyer_type", "sector_focus", "geography", "size_range")

# key, label, kind, default weight, dealbreaker, applies to (None: both), description
_TABLE: tuple[tuple[str, str, str, float, bool, BuyerType | None, str], ...] = (
    (
        "buyer_type",
        "Buyer type",
        "prefilter",
        1.0,
        False,
        None,
        "Structured type against the filter.",
    ),
    (
        "sector_focus",
        "Sector focus",
        "prefilter",
        2.0,
        False,
        None,
        "Structured sectors against the filter or the deal sector, confirmed in text when found.",
    ),
    (
        "geography",
        "Geography",
        "prefilter",
        1.0,
        False,
        None,
        "Structured geographies against the filter.",
    ),
    (
        "size_range",
        "Size range",
        "prefilter",
        1.0,
        False,
        None,
        "Market cap or AUM inside the filter range.",
    ),
    (
        "ticket_fit",
        "Ticket fit",
        "deep",
        3.0,
        True,
        BuyerType.FINANCIAL,
        "Indicative equity cheque as a share of fund size: below 5% or above 40% is not met, "
        "10% to 25% is the healthy band.",
    ),
    (
        "ev_ratio",
        "EV ratio",
        "deep",
        3.0,
        True,
        BuyerType.STRATEGIC,
        "Target EV over buyer EV: above 40% is transformational, above 60% is not met.",
    ),
    (
        "fund_lifecycle",
        "Fund lifecycle",
        "deep",
        1.0,
        False,
        BuyerType.FINANCIAL,
        "Investment period remaining, from fund documents.",
    ),
    (
        "recent_activity",
        "Recent activity",
        "deep",
        2.0,
        False,
        None,
        "Similar acquisitions found in dated sources.",
    ),
    (
        "integration_bandwidth",
        "Integration bandwidth",
        "deep",
        1.0,
        False,
        BuyerType.STRATEGIC,
        "Count of recent acquisitions in dated sources.",
    ),
    (
        "antitrust",
        "Antitrust",
        "deep",
        1.0,
        False,
        None,
        "Evaluated only when market share data is found in sources, otherwise unknown.",
    ),
    (
        "regulatory_fdi",
        "Regulatory and FDI",
        "deep",
        1.0,
        False,
        None,
        "Sovereignty, state ownership or defense exposure found in sources.",
    ),
)


def applies_to(key: str) -> BuyerType | None:
    """The buyer type a criterion is restricted to, `None` when it applies to both."""
    for row in _TABLE:
        if row[0] == key:
            return row[5]
    raise KeyError(key)


def build_criteria(weights: Mapping[str, float] | None = None) -> list[Criterion]:
    """The criteria table with the user weights applied. Unknown keys are an error here."""
    overrides = dict(weights or {})
    known = {row[0] for row in _TABLE}
    unknown = sorted(set(overrides) - known)
    if unknown:
        raise ValueError(f"unknown criterion keys in weights: {unknown}")
    criteria: list[Criterion] = []
    for key, label, kind, weight, dealbreaker, _, description in _TABLE:
        criteria.append(
            Criterion(
                key=key,
                label=label,
                kind="prefilter" if kind == "prefilter" else "deep",
                weight=overrides.get(key, weight),
                dealbreaker=dealbreaker,
                description=description,
            )
        )
    return criteria
