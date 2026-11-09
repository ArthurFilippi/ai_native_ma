"""Metric and period vocabulary used by the reranker, the understand step and the mock tasks.

Metric keys follow the ground truth naming (`revenue`, `gross_margin`, `top_customer_share`).
`kind` says which quantities can be a value of the metric: money, percent or count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MetricKind = Literal["money", "percent", "count"]


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    kind: MetricKind
    phrases: tuple[str, ...]


METRICS: tuple[MetricDef, ...] = (
    MetricDef(
        "revenue", "revenue", "money", ("net revenue", "net sales", "revenue", "sales", "turnover")
    ),
    MetricDef(
        "revenue_growth",
        "revenue growth",
        "percent",
        ("revenue growth", "sales growth", "growth rate"),
    ),
    MetricDef("gross_profit", "gross profit", "money", ("gross profit",)),
    MetricDef("gross_margin", "gross margin", "percent", ("gross profit margin", "gross margin")),
    MetricDef(
        "ebitda_margin", "EBITDA margin", "percent", ("adjusted ebitda margin", "ebitda margin")
    ),
    MetricDef("ebitda", "EBITDA", "money", ("adjusted ebitda", "ebitda")),
    MetricDef(
        "operating_income",
        "operating income",
        "money",
        ("operating income", "operating profit", "ebit"),
    ),
    MetricDef(
        "net_income",
        "net income",
        "money",
        ("net income", "net profit", "profit after tax", "net result"),
    ),
    MetricDef("net_debt", "net debt", "money", ("net financial debt", "net debt")),
    MetricDef("capex", "capital expenditure", "money", ("capital expenditure", "capex")),
    MetricDef("free_cash_flow", "free cash flow", "money", ("free cash flow",)),
    MetricDef("total_assets", "total assets", "money", ("total assets",)),
    MetricDef("equity_value", "equity value", "money", ("equity value",)),
    MetricDef("enterprise_value", "enterprise value", "money", ("enterprise value",)),
    MetricDef("purchase_price", "purchase price", "money", ("purchase price", "consideration")),
    MetricDef(
        "headcount",
        "headcount",
        "count",
        ("headcount", "employees", "full-time equivalents", "fte"),
    ),
    MetricDef(
        "top_customer_share",
        "largest customer share",
        "percent",
        ("largest customer", "top customer", "biggest customer", "customer concentration"),
    ),
    MetricDef(
        "top10_customer_share",
        "top ten customers share",
        "percent",
        ("top ten customers", "top 10 customers", "ten largest customers"),
    ),
    MetricDef(
        "customers", "number of customers", "count", ("number of customers", "active customers")
    ),
    MetricDef("market_share", "market share", "percent", ("market share",)),
    MetricDef(
        "fund_size",
        "fund size",
        "money",
        ("total commitments", "assets under management", "committed capital", "fund size", "aum"),
    ),
)

METRIC_BY_KEY: dict[str, MetricDef] = {m.key: m for m in METRICS}


def _phrase_pattern(phrase: str) -> str:
    return r"\s+".join(re.escape(part) for part in phrase.replace("-", " - ").split())


_PHRASE_TO_KEY: dict[str, str] = {p: m.key for m in METRICS for p in m.phrases}
_METRIC_RE = re.compile(
    r"\b(?:"
    + "|".join(
        _phrase_pattern(p).replace(r"\ -\ ", r"[-\s]")
        for p in sorted(_PHRASE_TO_KEY, key=len, reverse=True)
    )
    + r")s?\b",
    re.IGNORECASE,
)


def _key_of(matched: str) -> str:
    normalised = re.sub(r"[-\s]+", " ", matched.lower()).strip()
    if normalised in _PHRASE_TO_KEY:
        return _PHRASE_TO_KEY[normalised]
    return _PHRASE_TO_KEY[normalised.removesuffix("s")]


def find_metrics(text: str) -> list[tuple[str, int, int]]:
    """(metric key, start, end) of every metric mention, longest phrase wins at a position."""
    return [(_key_of(m.group(0)), m.start(), m.end()) for m in _METRIC_RE.finditer(text)]


def detect_metrics(text: str) -> list[str]:
    """Metric keys in order of first mention, without repeats."""
    seen: dict[str, None] = {}
    for key, _, _ in find_metrics(text):
        seen.setdefault(key)
    return list(seen)


# ---- periods ---------------------------------------------------------------------------------

_MONTHS = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DATE_RE = re.compile(
    rf"\b(?:\d{{1,2}}\s+)?{_MONTHS}\.?\s+(?:\d{{1,2}},\s*)?\d{{4}}\b", re.IGNORECASE
)
_FY_RE = re.compile(r"\bFY\s?'?(\d{4}|\d{2})\b(?!\d)", re.IGNORECASE)
_FISCAL_RE = re.compile(r"\b(?:fiscal|financial)(?:\s+year)?\s+(\d{4})\b", re.IGNORECASE)
_HALF_RE = re.compile(r"\b(H[12])\s?(?:FY\s?)?(\d{4})\b", re.IGNORECASE)
_QUARTER_RE = re.compile(r"\b(Q[1-4])\s?(?:FY\s?)?(\d{4})\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?<![\w/.-])(?:19|20)\d{2}(?![\w/-]|[.,]\d)")


def _full_year(digits: str) -> str:
    return digits if len(digits) == 4 else f"20{digits}"


def find_periods(text: str) -> list[tuple[str, int, int]]:
    """(normalised period, start, end). `FY2024`, `fiscal 2024`, `in 2024` become `FY2024`;
    half years and quarters become `H1 2024` and `Q3 2024`. Calendar dates are not periods."""
    taken: list[tuple[int, int]] = [(m.start(), m.end()) for m in _DATE_RE.finditer(text)]
    found: list[tuple[str, int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= a or start >= b for a, b in taken)

    def add(label: str, match: re.Match[str]) -> None:
        if free(match.start(), match.end()):
            taken.append((match.start(), match.end()))
            found.append((label, match.start(), match.end()))

    for m in _HALF_RE.finditer(text):
        add(f"{m.group(1).upper()} {m.group(2)}", m)
    for m in _QUARTER_RE.finditer(text):
        add(f"{m.group(1).upper()} {m.group(2)}", m)
    for m in _FY_RE.finditer(text):
        add(f"FY{_full_year(m.group(1))}", m)
    for m in _FISCAL_RE.finditer(text):
        add(f"FY{m.group(1)}", m)
    for m in _YEAR_RE.finditer(text):
        add(f"FY{m.group(0)}", m)
    return sorted(found, key=lambda item: item[1])


def detect_periods(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for label, _, _ in find_periods(text):
        seen.setdefault(label)
    return list(seen)


def previous_period(period: str) -> str | None:
    """`FY2024` to `FY2023`. Half years and quarters have no simple predecessor here."""
    if period.startswith("FY") and period[2:].isdigit():
        return f"FY{int(period[2:]) - 1}"
    return None
