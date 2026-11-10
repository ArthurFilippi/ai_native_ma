"""KPI definitions for an industrial company: income statement, cash flow, balance sheet.

Ported as data from the legacy `default_kpis.py` (same ids, formulas and dependencies), pruned to
the lines of a P&L, balance sheet and cash flow, and re-typed as `KpiDef`. Legacy unit labels map
to `EUR m` (currency), `%` (percentage), `x` (ratio) and `count`. Sector specific, sales funnel
and subscription KPIs were dropped: nothing in the synthetic industrial data room exercises them.

`KPI_LABELS` lists the wordings used to recognise a KPI in text and in table rows (lowercase).
The aliases are matched on whole words, longest first, so `net debt` never reads as `debt`.
"""

from __future__ import annotations

from typing import Final

from ainma.contracts import KpiDef

DEFAULT_PERIODS: Final[tuple[str, ...]] = ("FY2020", "FY2021", "FY2022", "FY2023", "FY2024")

EUR_M: Final = "EUR m"
PERCENT: Final = "%"
RATIO: Final = "x"
COUNT: Final = "count"


def _extract(kpi_id: str, name: str, category: str, unit: str) -> KpiDef:
    return KpiDef(id=kpi_id, name=name, category=category, unit=unit, kind="extract")


def _compute(
    kpi_id: str, name: str, category: str, unit: str, formula: str, depends_on: list[str]
) -> KpiDef:
    return KpiDef(
        id=kpi_id,
        name=name,
        category=category,
        unit=unit,
        kind="compute",
        formula=formula,
        depends_on=depends_on,
    )


_IS = "Income Statement"
_CF = "Cash Flow"
_BS = "Balance Sheet"

# Constants: never mutated. `kpi_definitions()` hands out copies.
_DEFINITIONS: Final[tuple[KpiDef, ...]] = (
    _extract("revenue", "Revenue", _IS, EUR_M),
    _extract("cogs", "Cost of Goods Sold", _IS, EUR_M),
    _compute("gross_profit", "Gross Profit", _IS, EUR_M, "revenue - cogs", ["revenue", "cogs"]),
    _compute(
        "gross_margin",
        "Gross Margin",
        _IS,
        PERCENT,
        "(gross_profit / revenue) * 100",
        ["gross_profit", "revenue"],
    ),
    _extract("ebitda", "EBITDA", _IS, EUR_M),
    _compute(
        "ebitda_margin",
        "EBITDA Margin",
        _IS,
        PERCENT,
        "(ebitda / revenue) * 100",
        ["ebitda", "revenue"],
    ),
    _extract("ebit", "EBIT", _IS, EUR_M),
    _extract("interest_expense", "Interest Expense", _IS, EUR_M),
    _compute(
        "interest_coverage",
        "Interest Coverage",
        _IS,
        RATIO,
        "ebit / interest_expense",
        ["ebit", "interest_expense"],
    ),
    _extract("net_income", "Net Income", _IS, EUR_M),
    _compute(
        "net_margin",
        "Net Margin",
        _IS,
        PERCENT,
        "(net_income / revenue) * 100",
        ["net_income", "revenue"],
    ),
    _extract("operating_cash_flow", "Operating Cash Flow", _CF, EUR_M),
    _extract("capex", "Capital Expenditures", _CF, EUR_M),
    _compute(
        "free_cash_flow",
        "Free Cash Flow",
        _CF,
        EUR_M,
        "operating_cash_flow - capex",
        ["operating_cash_flow", "capex"],
    ),
    _compute(
        "capex_intensity",
        "Capex Intensity",
        _CF,
        PERCENT,
        "(capex / revenue) * 100",
        ["capex", "revenue"],
    ),
    _extract("current_assets", "Current Assets", _BS, EUR_M),
    _extract("current_liabilities", "Current Liabilities", _BS, EUR_M),
    _compute(
        "working_capital",
        "Working Capital",
        _BS,
        EUR_M,
        "current_assets - current_liabilities",
        ["current_assets", "current_liabilities"],
    ),
    _compute(
        "working_capital_ratio",
        "Working Capital Ratio",
        _BS,
        RATIO,
        "current_assets / current_liabilities",
        ["current_assets", "current_liabilities"],
    ),
    _extract("cash", "Cash & Cash Equivalents", _BS, EUR_M),
    _extract("total_debt", "Total Debt", _BS, EUR_M),
    _compute("net_debt", "Net Debt", _BS, EUR_M, "total_debt - cash", ["total_debt", "cash"]),
    _extract("total_assets", "Total Assets", _BS, EUR_M),
    _extract("total_equity", "Total Equity", _BS, EUR_M),
    _compute("leverage", "Leverage", _BS, RATIO, "net_debt / ebitda", ["net_debt", "ebitda"]),
    _compute(
        "roe",
        "Return on Equity",
        "Returns",
        PERCENT,
        "(net_income / total_equity) * 100",
        ["net_income", "total_equity"],
    ),
    _compute(
        "roa",
        "Return on Assets",
        "Returns",
        PERCENT,
        "(net_income / total_assets) * 100",
        ["net_income", "total_assets"],
    ),
    _extract("total_headcount", "Total Headcount", "Operational", COUNT),
    _compute(
        "revenue_per_employee",
        "Revenue per Employee",
        "Operational",
        "EUR m",
        "revenue / total_headcount",
        ["revenue", "total_headcount"],
    ),
    _extract("customer_concentration", "Customer Concentration", "Risk", PERCENT),
)

KPI_LABELS: Final[dict[str, tuple[str, ...]]] = {
    "revenue": ("net revenue", "net revenues", "total revenue", "revenues", "revenue", "net sales"),
    "cogs": ("cost of goods sold", "cost of sales", "cost of revenue", "cogs"),
    "gross_profit": ("gross profit",),
    "gross_margin": ("gross profit margin", "gross margin"),
    "ebitda": ("ebitda",),
    "ebitda_margin": ("ebitda margin",),
    "ebit": ("operating income", "operating profit", "ebit"),
    "interest_expense": ("net interest expense", "interest expenses", "interest expense"),
    "interest_coverage": ("interest coverage", "interest cover"),
    "net_income": ("net income", "net profit", "net earnings", "profit for the year"),
    "net_margin": ("net margin", "net income margin"),
    "operating_cash_flow": (
        "operating cash flow",
        "cash flow from operations",
        "cash flow from operating activities",
        "net cash from operating activities",
    ),
    "capex": ("capital expenditures", "capital expenditure", "capex"),
    "free_cash_flow": ("free cash flow", "fcf"),
    "capex_intensity": ("capex intensity",),
    "current_assets": ("total current assets", "current assets"),
    "current_liabilities": ("total current liabilities", "current liabilities"),
    "working_capital": ("net working capital", "working capital"),
    "working_capital_ratio": ("working capital ratio", "current ratio"),
    "cash": ("cash and cash equivalents", "cash & cash equivalents", "cash"),
    "total_debt": ("total debt", "gross debt", "financial debt"),
    "net_debt": ("net financial debt", "net debt"),
    "total_assets": ("total assets",),
    "total_equity": ("total shareholders' equity", "shareholders' equity", "total equity"),
    "leverage": ("net leverage", "net debt to ebitda", "leverage"),
    "roe": ("return on equity", "roe"),
    "roa": ("return on assets", "roa"),
    "total_headcount": ("total headcount", "number of employees", "headcount", "employees"),
    "revenue_per_employee": ("revenue per employee",),
    "customer_concentration": (
        "customer concentration",
        "largest customer",
        "top customer",
    ),
}


def kpi_definitions() -> list[KpiDef]:
    """Fresh copies of the default definitions, in the order of the income statement first."""
    return [d.model_copy(deep=True) for d in _DEFINITIONS]
