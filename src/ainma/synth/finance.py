"""Five year financial model of a fictional company, in tenths of EUR m (integer arithmetic).

All reported numbers are integers in tenths, so every sum, difference and printed value is exact
and the KPI truth table is exactly what the spreadsheet shows.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from ainma.synth.common import YEARS

# The 20 KPIs of the truth table. Ids, units and kinds come from the legacy definitions
# (`default_kpis.py`, 62 entries). Units are written EUR m, % and x.
KPI_IDS: list[tuple[str, str, str]] = [
    ("revenue", "EUR m", "extract"),
    ("cogs", "EUR m", "extract"),
    ("gross_profit", "EUR m", "compute"),
    ("gross_margin", "%", "compute"),
    ("ebitda", "EUR m", "extract"),
    ("ebitda_margin", "%", "compute"),
    ("ebit", "EUR m", "extract"),
    ("net_income", "EUR m", "extract"),
    ("net_margin", "%", "compute"),
    ("operating_cash_flow", "EUR m", "extract"),
    ("capex", "EUR m", "extract"),
    ("free_cash_flow", "EUR m", "compute"),
    ("cash", "EUR m", "extract"),
    ("total_debt", "EUR m", "extract"),
    ("net_debt", "EUR m", "compute"),
    ("leverage", "x", "compute"),
    ("total_assets", "EUR m", "extract"),
    ("total_equity", "EUR m", "extract"),
    ("interest_expense", "EUR m", "extract"),
    ("interest_coverage", "x", "compute"),
]


@dataclass
class Financials:
    years: list[str]
    # income statement
    revenue: list[int]
    cogs: list[int]
    gross_profit: list[int]
    sga: list[int]
    ebitda: list[int]
    da: list[int]
    ebit: list[int]
    interest: list[int]
    ebt: list[int]
    tax: list[int]
    net_income: list[int]
    # balance sheet
    cash: list[int]
    receivables: list[int]
    inventory: list[int]
    current_assets: list[int]
    ppe: list[int]
    other_nc: list[int]
    total_assets: list[int]
    payables: list[int]
    other_cl: list[int]
    st_debt: list[int]
    current_liabilities: list[int]
    lt_debt: list[int]
    total_debt: list[int]
    equity: list[int]
    total_le: list[int]
    # cash flow
    d_wc: list[int]
    ocf: list[int]
    capex: list[int]

    def idx(self, year: str) -> int:
        return self.years.index(year)


def _u(rng: Random, lo: float, hi: float) -> float:
    return lo + (hi - lo) * rng.random()


def generate_financials(
    rng: Random,
    *,
    revenue_last: int | None = None,
    revenue_prev: int | None = None,
    gross_margin_last: float | None = None,
) -> Financials:
    """`revenue_last` and `revenue_prev` (tenths) pin FY2024 and FY2023 (seed 1234 anchors)."""
    last = revenue_last if revenue_last is not None else int(_u(rng, 900, 4000))
    growth = [_u(rng, 0.02, 0.10) for _ in range(4)]
    rev = [0] * 5
    rev[4] = last
    if revenue_prev is not None:
        rev[3] = revenue_prev
    else:
        rev[3] = round(rev[4] / (1 + growth[3]))
    for i in (2, 1, 0):
        rev[i] = round(rev[i + 1] / (1 + growth[i]))
    gm = [_u(rng, 0.29, 0.44)]
    for _ in range(4):
        gm.append(min(0.46, max(0.27, gm[-1] + _u(rng, -0.015, 0.02))))
    if gross_margin_last is not None:
        gm[4] = gross_margin_last
    sga_ratio = _u(rng, 0.17, 0.25)
    gp = [round(r * g) for r, g in zip(rev, gm, strict=True)]
    cogs = [r - g for r, g in zip(rev, gp, strict=True)]
    sga = [round(r * (sga_ratio + _u(rng, -0.01, 0.01))) for r in rev]
    ebitda = [g - s for g, s in zip(gp, sga, strict=True)]
    for i in range(5):  # keep EBITDA margin in a plausible band
        if ebitda[i] < rev[i] * 0.08:
            sga[i] = gp[i] - round(rev[i] * 0.09)
            ebitda[i] = gp[i] - sga[i]
    da = [round(r * _u(rng, 0.028, 0.045)) for r in rev]
    ebit = [e - d for e, d in zip(ebitda, da, strict=True)]
    total_debt = [round(e * _u(rng, 1.2, 2.6)) for e in ebitda]
    interest = [round(d * _u(rng, 0.035, 0.055)) for d in total_debt]
    ebt = [b - i for b, i in zip(ebit, interest, strict=True)]
    tax = [round(max(0, t) * 0.27) for t in ebt]
    ni = [t - x for t, x in zip(ebt, tax, strict=True)]
    cash = [round(r * _u(rng, 0.04, 0.09)) for r in rev]
    receivables = [round(r * _u(rng, 0.12, 0.17)) for r in rev]
    inventory = [round(r * _u(rng, 0.10, 0.16)) for r in rev]
    current_assets = [a + b + c for a, b, c in zip(cash, receivables, inventory, strict=True)]
    ppe = [round(r * _u(rng, 0.42, 0.65)) for r in rev]
    other_nc = [round(r * _u(rng, 0.04, 0.07)) for r in rev]
    total_assets = [a + b + c for a, b, c in zip(current_assets, ppe, other_nc, strict=True)]
    payables = [round(r * _u(rng, 0.08, 0.12)) for r in rev]
    other_cl = [round(r * _u(rng, 0.03, 0.05)) for r in rev]
    st_debt = [round(d * 0.2) for d in total_debt]
    lt_debt = [d - s for d, s in zip(total_debt, st_debt, strict=True)]
    current_liabilities = [a + b + c for a, b, c in zip(payables, other_cl, st_debt, strict=True)]
    equity = [
        ta - cl - lt for ta, cl, lt in zip(total_assets, current_liabilities, lt_debt, strict=True)
    ]
    total_le = [cl + lt + e for cl, lt, e in zip(current_liabilities, lt_debt, equity, strict=True)]
    d_wc = [round(r * _u(rng, -0.005, 0.02)) for r in rev]
    ocf = [n + d - w for n, d, w in zip(ni, da, d_wc, strict=True)]
    capex = [round(r * _u(rng, 0.03, 0.055)) for r in rev]
    return Financials(
        years=list(YEARS), revenue=rev, cogs=cogs, gross_profit=gp, sga=sga, ebitda=ebitda,
        da=da, ebit=ebit, interest=interest, ebt=ebt, tax=tax, net_income=ni, cash=cash,
        receivables=receivables, inventory=inventory, current_assets=current_assets, ppe=ppe,
        other_nc=other_nc, total_assets=total_assets, payables=payables, other_cl=other_cl,
        st_debt=st_debt, current_liabilities=current_liabilities, lt_debt=lt_debt,
        total_debt=total_debt, equity=equity, total_le=total_le, d_wc=d_wc, ocf=ocf, capex=capex,
    )


def tenths(values: list[int]) -> list[float]:
    return [v / 10 for v in values]


def kpi_truth_values(fin: Financials, year: str) -> dict[str, float]:
    """Exact KPI values for one year, from the same integers the spreadsheet prints."""
    i = fin.idx(year)
    t = lambda xs: xs[i] / 10  # noqa: E731
    rev, gp, ebitda, ni = t(fin.revenue), t(fin.gross_profit), t(fin.ebitda), t(fin.net_income)
    debt, cash = t(fin.total_debt), t(fin.cash)
    return {
        "revenue": rev,
        "cogs": t(fin.cogs),
        "gross_profit": gp,
        "gross_margin": round(gp / rev * 100, 4),
        "ebitda": ebitda,
        "ebitda_margin": round(ebitda / rev * 100, 4),
        "ebit": t(fin.ebit),
        "net_income": ni,
        "net_margin": round(ni / rev * 100, 4),
        "operating_cash_flow": t(fin.ocf),
        "capex": t(fin.capex),
        "free_cash_flow": round(t(fin.ocf) - t(fin.capex), 4),
        "cash": cash,
        "total_debt": debt,
        "net_debt": round(debt - cash, 4),
        "leverage": round((debt - cash) / ebitda, 4),
        "total_assets": t(fin.total_assets),
        "total_equity": t(fin.equity),
        "interest_expense": t(fin.interest),
        "interest_coverage": round(t(fin.ebit) / t(fin.interest), 4),
    }
