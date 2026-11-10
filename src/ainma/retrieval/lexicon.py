"""Metric and period vocabulary used by the reranker, the understand step and the mock tasks.

Metric keys follow the ground truth naming (`revenue`, `gross_margin`, `top_customer_share`).
`kind` says which quantities can be a value of the metric: money, percent or count.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

MetricKind = Literal["money", "percent", "count", "year", "multiple", "duration"]


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    kind: MetricKind
    phrases: tuple[str, ...]
    static: bool = False  # a property of the entity, not of a period (fund vintage, process length)


# A small glossary of financial terms: each metric lists the words a document or a question uses
# for it, including the usual paraphrases ("turnover", "workforce", "borrowings less cash").
# Labels are the canonical names a claim uses. Longer phrases win over shorter ones, and a number
# is only given to a metric of the same kind (a percent never becomes a revenue), which is what
# keeps "38.5 percent of sales" from being read as revenue.
METRICS: tuple[MetricDef, ...] = (
    MetricDef(
        "revenue",
        "revenue",
        "money",
        ("net revenue", "net sales", "total sales", "revenue", "turnover", "top line", "sales"),
    ),
    MetricDef(
        "revenue_growth",
        "revenue growth",
        "percent",
        ("revenue growth", "sales growth", "growth rate"),
    ),
    MetricDef("gross_profit", "gross profit", "money", ("gross profit",)),
    MetricDef(
        "gross_margin",
        "gross margin",
        "percent",
        (
            "gross profit margin",
            "gross margin",
            "profit after cost of goods sold",
            "after direct production costs",
            "direct production costs",
        ),
    ),
    MetricDef(
        "ebitda_margin",
        "EBITDA margin",
        "percent",
        (
            "adjusted ebitda margin",
            "ebitda margin",
            "operating earnings before depreciation",
            "operating profit before depreciation",
        ),
    ),
    MetricDef(
        "adjusted_ebitda",
        "adjusted EBITDA",
        "money",
        ("adjusted ebitda", "underlying operating earnings"),
    ),
    MetricDef(
        "ebitda",
        "EBITDA",
        "money",
        (
            "ebitda",
            "earnings before interest, tax, depreciation and amortisation",
            "earnings before interest, tax, depreciation and amortization",
            "operating earnings before depreciation and amortisation",
            "operating earnings before depreciation and amortization",
        ),
    ),
    MetricDef(
        "order_backlog",
        "order backlog",
        "money",
        (
            "order backlog",
            "order book",
            "contracted orders not yet delivered",
            "contracted but undelivered business",
        ),
    ),
    MetricDef(
        "export_share",
        "export share",
        "percent",
        ("export share", "sales abroad", "foreign customers", "exports"),
    ),
    MetricDef(
        "market_cap",
        "market capitalisation",
        "money",
        (
            "market capitalisation",
            "market capitalization",
            "market cap",
            "on the exchange",
            "by the market",
        ),
    ),
    MetricDef(
        "production_sites",
        "production sites",
        "count",
        ("production sites", "manufacturing sites", "plants"),
    ),
    MetricDef(
        "portfolio_companies",
        "portfolio companies",
        "count",
        ("portfolio companies", "operating businesses"),
    ),
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
    MetricDef(
        "net_debt",
        "net debt",
        "money",
        ("net financial debt", "net debt", "borrowings less cash"),
    ),
    MetricDef(
        "capex",
        "capital expenditure",
        "money",
        (
            "capital expenditure",
            "capex",
            "investment in property, plant and equipment",
            "invest in property, plant and equipment",
            "invested in property, plant and equipment",
        ),
    ),
    MetricDef("free_cash_flow", "free cash flow", "money", ("free cash flow",)),
    MetricDef("total_assets", "total assets", "money", ("total assets",)),
    MetricDef(
        "equity_value",
        "equity value",
        "money",
        ("equity value", "shareholders would receive", "shareholders"),
    ),
    MetricDef(
        "enterprise_value",
        "enterprise value",
        "money",
        ("enterprise value", "cash-free and debt-free"),
    ),
    MetricDef("purchase_price", "purchase price", "money", ("purchase price", "consideration")),
    MetricDef(
        "headcount",
        "headcount",
        "count",
        (
            "headcount",
            "employees",
            "workforce",
            "employed",
            "employ",
            "full-time equivalents",
            "fte",
        ),
    ),
    MetricDef(
        "top_customer_share",
        "largest customer share",
        "percent",
        (
            "largest customer",
            "top customer",
            "biggest customer",
            "biggest client",
            "single client",
            "customer concentration",
        ),
    ),
    MetricDef(
        "top10_customer_share",
        "top ten customers share",
        "percent",
        (
            "top ten customers",
            "top 10 customers",
            "ten largest customers",
            "leading ten clients",
        ),
    ),
    MetricDef(
        "customers", "number of customers", "count", ("number of customers", "active customers")
    ),
    MetricDef(
        "market_share",
        "market share",
        "percent",
        ("market share", "of european sales", "main european segment", "european segment"),
    ),
    MetricDef(
        "fund_size",
        "assets under management",
        "money",
        (
            "total commitments",
            "assets under management",
            "committed capital",
            "fund size",
            "aum",
            "administers",
            "administer",
            "to manage",
            "assets of",
        ),
    ),
    MetricDef(
        "fund_vintage_year",
        "fund vintage year",
        "year",
        ("vintage year", "investor pool", "fund was launched", "investment vehicle"),
        static=True,
    ),
    MetricDef(
        "investment_period_end_year",
        "investment period end",
        "year",
        (
            "investment period",
            "new platform deals",
            "new platform investments",
        ),
        static=True,
    ),
    MetricDef(
        "ticket_min",
        "minimum ticket",
        "money",
        ("minimum equity ticket", "smallest equity cheque", "minimum ticket"),
        static=True,
    ),
    MetricDef(
        "ticket_max",
        "maximum ticket",
        "money",
        ("maximum equity ticket", "largest equity cheque", "maximum ticket"),
        static=True,
    ),
    MetricDef(
        "process_weeks",
        "process duration",
        "duration",
        (
            "process duration",
            "from teaser to signing",
            "from first teaser to signature",
            "between teaser and signature",
            "teaser to signature",
            "usually last",
            "typically last",
        ),
        static=True,
    ),
    MetricDef(
        "nda_term_months",
        "confidentiality term",
        "duration",
        ("confidentiality term", "secrecy obligations"),
        static=True,
    ),
    MetricDef(
        "bidder_rounds",
        "bidding rounds",
        "count",
        ("bidding rounds", "stages of offers"),
        static=True,
    ),
    MetricDef(
        "break_fee_pct",
        "break fee",
        "percent",
        ("break fee", "seller walking away pays"),
        static=True,
    ),
    MetricDef(
        "precedent_multiple",
        "EV to EBITDA multiple",
        "multiple",
        ("ev to ebitda multiple", "buyers paid", "times operating earnings before depreciation"),
        static=True,
    ),
)

# Phrases that state a range: the first amount is the minimum, the second the maximum.
RANGE_PHRASES: dict[str, tuple[str, str]] = {
    "equity ticket": ("ticket_min", "ticket_max"),
    "equity cheque": ("ticket_min", "ticket_max"),
}

METRIC_BY_KEY: dict[str, MetricDef] = {m.key: m for m in METRICS}


def _phrase_pattern(phrase: str) -> str:
    words = phrase.replace(",", " ").replace("-", " - ").split()
    return r"[\s,]+".join(re.escape(part) for part in words).replace(r"[\s,]+\-[\s,]+", r"[-\s]")


_PHRASE_TO_KEY: dict[str, str] = {p: m.key for m in METRICS for p in m.phrases}
_METRIC_RE = re.compile(
    r"\b(?:"
    + "|".join(_phrase_pattern(p) for p in sorted(_PHRASE_TO_KEY, key=len, reverse=True))
    + r")(?:s|es)?\b",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in RANGE_PHRASES) + r")(?:s)?\b", re.IGNORECASE
)


def _normal(text: str) -> str:
    return re.sub(r"[-,\s]+", " ", text.lower()).strip()


_NORMAL_TO_KEY: dict[str, str] = {_normal(p): k for p, k in _PHRASE_TO_KEY.items()}


def _key_of(matched: str) -> str:
    normalised = _normal(matched)
    for candidate in (normalised, normalised.removesuffix("s"), normalised.removesuffix("es")):
        if candidate in _NORMAL_TO_KEY:
            return _NORMAL_TO_KEY[candidate]
    raise KeyError(matched)


def find_metrics(text: str) -> list[tuple[str, int, int]]:
    """(metric key, start, end) of every metric mention, longest phrase wins at a position."""
    return [(_key_of(m.group(0)), m.start(), m.end()) for m in _METRIC_RE.finditer(text)]


def find_range_phrases(text: str) -> list[tuple[tuple[str, str], int, int]]:
    """Mentions of a range phrase (`equity ticket`): ((min key, max key), start, end)."""
    return [
        (RANGE_PHRASES[_normal(m.group(0)).removesuffix("s")], m.start(), m.end())
        for m in _RANGE_RE.finditer(text)
    ]


def concept_tokens(keys: Iterable[str]) -> str:
    """One purely alphabetic token per metric (`xmetricebitda`), to append to a text that talks
    about the metric in other words. It lets a keyword retriever (BM25, LSA) match `turnover`
    with `revenue` and `earnings before interest, tax, depreciation and amortisation` with
    `EBITDA`, the way a neural embedder matches paraphrases."""
    names = (
        "".join(chr(ord("a") + int(c)) if c.isdigit() else c for c in key.replace("_", ""))
        for key in dict.fromkeys(keys)
    )
    return " ".join(f"xmetric{name}" for name in names)


def detect_metrics(text: str) -> list[str]:
    """Metric keys in order of first mention, without repeats."""
    seen: dict[str, None] = {}
    for key, _, _ in find_metrics(text):
        seen.setdefault(key)
    return list(seen)


_SHARE_CUE = re.compile(
    r"\b(?:share|percent|percentage|proportion|portion|how much of)\b", re.IGNORECASE
)
_CONDITION_CUE = re.compile(r"\b(?:after|before|excluding|net of|less)\s+$", re.IGNORECASE)


def target_metrics(question: str) -> list[str]:
    """The metrics a question asks for, which is not every metric it mentions.

    `What share of FY2024 revenue came from the largest customer?` asks for the customer share, the
    revenue is the base of the ratio; `How much would shareholders receive after net debt is
    settled?` asks for the equity value, net debt is a condition.
    """
    mentions = find_metrics(question)
    keys = list(dict.fromkeys(k for k, _, _ in mentions))
    if len(keys) < 2:
        return keys
    kept = [
        k
        for k in keys
        if not all(
            _CONDITION_CUE.search(question[:start]) for key, start, _ in mentions if key == k
        )
    ] or keys
    if _SHARE_CUE.search(question):
        ratios = [k for k in kept if METRIC_BY_KEY[k].kind == "percent"]
        kept = ratios or kept
    return kept


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
_YEAR_END_RE = re.compile(
    rf"\byear\s+ended\s+(?:\d{{1,2}}\s+)?{_MONTHS}\.?\s+(\d{{4}})\b", re.IGNORECASE
)
_YEAR_RE = re.compile(r"(?<![\w/.-])(?:19|20)\d{2}(?![\w/-]|[.,]\d)")


def _full_year(digits: str) -> str:
    return digits if len(digits) == 4 else f"20{digits}"


def find_periods(text: str) -> list[tuple[str, int, int]]:
    """(normalised period, start, end). `FY2024`, `fiscal 2024`, `in 2024` become `FY2024`;
    half years and quarters become `H1 2024` and `Q3 2024`. Calendar dates are not periods."""
    found: list[tuple[str, int, int]] = []
    taken: list[tuple[int, int]] = []
    for m in _YEAR_END_RE.finditer(text):  # "the year ended 31 December 2024" is FY2024
        taken.append((m.start(), m.end()))
        found.append((f"FY{m.group(1)}", m.start(), m.end()))
    taken.extend((m.start(), m.end()) for m in _DATE_RE.finditer(text))

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


def date_spans(text: str) -> list[tuple[int, int]]:
    """Spans of calendar dates (`31 December 2024`) and of `year ended ...` expressions, whose
    numbers are not quantities."""
    return [m.span() for m in _DATE_RE.finditer(text)] + [
        m.span() for m in _YEAR_END_RE.finditer(text)
    ]


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
