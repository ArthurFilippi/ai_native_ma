"""The fictional world of one seed: target companies, buyers, acquisitions, planted attributes.

Everything here is structured data. Documents and ground truth are derived from it, so truth
never depends on what the text generator happened to write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from random import Random
from typing import Literal, cast

from ainma.contracts import BuyerProfile, BuyerType
from ainma.synth.common import DEMO_SEED, REFERENCE_DATE, Params, rng_for
from ainma.synth.finance import Financials, generate_financials
from ainma.synth.lang import CITIES, NamePool


@dataclass(frozen=True)
class Sector:
    label: str
    activity: str
    products: list[str]
    customers: list[str]
    site: str


_SECTOR_DATA: dict[str, dict[str, object]] = {
    "industrial_components": {
        "label": "industrial components",
        "activity": "producer of precision industrial components",
        "products": ["drive shafts", "hydraulic valves", "bearing assemblies", "sealing systems"],
        "customers": ["machine builders", "agricultural equipment makers", "rail suppliers"],
        "site": "production site",
    },
    "software": {
        "label": "software",
        "activity": "provider of workflow software for mid-sized enterprises",
        "products": ["planning modules", "reporting suites", "integration gateways", "audit tools"],
        "customers": ["manufacturers", "retailers", "public bodies"],
        "site": "development centre",
    },
    "logistics": {
        "label": "logistics",
        "activity": "operator of contract logistics and freight networks",
        "products": [
            "pallet distribution",
            "cold chain handling",
            "cross dock services",
            "last mile delivery",
        ],
        "customers": ["retail chains", "food producers", "online sellers"],
        "site": "logistics hub",
    },
    "packaging": {
        "label": "packaging",
        "activity": "manufacturer of consumer and industrial packaging",
        "products": ["folding cartons", "rigid containers", "protective inserts", "label systems"],
        "customers": ["beverage makers", "cosmetics brands", "electronics assemblers"],
        "site": "converting plant",
    },
    "medical_devices": {
        "label": "medical devices",
        "activity": "maker of non-invasive medical devices",
        "products": [
            "monitoring units",
            "diagnostic sensors",
            "sterile disposables",
            "imaging accessories",
        ],
        "customers": ["hospital groups", "clinic networks", "distributors"],
        "site": "assembly facility",
    },
    "food": {
        "label": "food and beverage",
        "activity": "producer of branded and private label foods",
        "products": ["bakery goods", "ready meals", "dairy alternatives", "snack lines"],
        "customers": ["supermarket chains", "discount retailers", "food service groups"],
        "site": "food plant",
    },
    "water_systems": {
        "label": "water systems",
        "activity": "supplier of water treatment and metering systems",
        "products": ["filtration skids", "smart meters", "dosing pumps", "monitoring probes"],
        "customers": ["utilities", "municipalities", "industrial plants"],
        "site": "manufacturing site",
    },
    "automotive_parts": {
        "label": "automotive parts",
        "activity": "supplier of aftermarket and original equipment automotive parts",
        "products": ["brake components", "thermal modules", "steering parts", "sensor housings"],
        "customers": ["vehicle makers", "tier one suppliers", "parts wholesalers"],
        "site": "machining plant",
    },
}
SECTORS: dict[str, Sector] = {
    k: Sector(
        str(v["label"]),
        str(v["activity"]),
        list(cast(list[str], v["products"])),
        list(cast(list[str], v["customers"])),
        str(v["site"]),
    )
    for k, v in _SECTOR_DATA.items()
}
SECTOR_KEYS = list(SECTORS)
GEOGRAPHIES = [
    "Central Europe",
    "Nordics",
    "UK and Ireland",
    "Southern Europe",
    "North America",
    "Asia Pacific",
]
AURORA_SECTOR = "industrial_components"
AURORA_REGION = "Central Europe"

DEAL_PLAN: list[tuple[str, str, str, str]] = [
    # deal id, project, sector, suffix of the company name
    ("deal_aurora", "Aurora", "industrial_components", "Components"),
    ("deal_borealis", "Borealis", "software", "Analytics"),
    ("deal_cygnus", "Cygnus", "logistics", "Logistics"),
    ("deal_draco", "Draco", "packaging", "Packaging"),
    ("deal_eridanus", "Eridanus", "medical_devices", "Medical"),
    ("deal_fornax", "Fornax", "food", "Foods"),
    ("deal_gemini", "Gemini", "water_systems", "Water Systems"),
    ("deal_hydra", "Hydra", "automotive_parts", "Automotive"),
    ("deal_lyra", "Lyra", "packaging", "Containers"),
]
# Deals with an executed SPA replacing a draft; the others get a withdrawn press release.
SPA_DEALS = {"deal_aurora", "deal_borealis", "deal_draco", "deal_fornax", "deal_hydra"}
WITHDRAWN_PR_DEALS = {"deal_aurora", "deal_cygnus", "deal_eridanus", "deal_gemini", "deal_lyra"}
OLD_DECK_DEALS = {"deal_borealis", "deal_cygnus", "deal_eridanus", "deal_hydra", "deal_lyra"}


@dataclass
class Company:
    deal_id: str
    project: str
    key: str
    name: str
    legal: str
    sector: str
    hq: str
    ceo: str
    cfo: str
    founded: int
    fin: Financials
    headcount: list[int]  # FY2020..FY2024
    plants: int
    backlog: float
    top_customer: float
    top10: float
    export_share_old: float  # FY2023, stated only in an old press article
    plants_old: int  # FY2022, stated only in an old prior-year deck
    distractor: str  # similarly named company
    distractor_revenue: float
    ev: float
    equity: float
    draft_ev: float
    press_revenue: float
    press_ebitda: float
    press_headcount: int
    orig_pr_ebitda: float  # withdrawn press release figure
    restated_prior_revenue: float | None  # hard negative: restated FY2023 revenue
    products: list[str]
    customers: list[str]
    sector_label: str = ""
    site: str = ""

    @property
    def revenue_last(self) -> float:
        return self.fin.revenue[4] / 10

    @property
    def ebitda_last(self) -> float:
        return self.fin.ebitda[4] / 10

    @property
    def net_debt_last(self) -> float:
        return (self.fin.total_debt[4] - self.fin.cash[4]) / 10

    @property
    def gross_margin_last(self) -> float:
        return round(self.fin.gross_profit[4] / self.fin.revenue[4] * 100, 1)

    def margin(self, series: list[int], i: int) -> float:
        return round(series[i] / self.fin.revenue[i] * 100, 1)


@dataclass(frozen=True)
class Acquisition:
    when: date
    sector: str
    target: str


RegState = Literal["sovereign", "defense", "private", "unspecified"]


@dataclass
class Buyer:
    profile: BuyerProfile
    investment_end: int | None  # fund investment period end year (financial, unlisted)
    end_stated: bool
    market_share: float | None  # strategic, stated in the annual report when `share_stated`
    share_stated: bool
    reg_state: RegState
    acquisitions: list[Acquisition]
    revenue: float  # strategic, EUR m FY2024
    employees: int
    portfolio: int
    article_conflict: float | None  # size stated by the trade article when it disagrees
    old_pr: bool
    old_filing: bool
    withdrawn_pr: bool
    aum_old: float  # FY2022 size, only in the old press release
    employees_old: int  # FY2021, only in the old filing
    extra_article: bool
    reg_in_profile: bool = True
    share_in_filing: bool = False


@dataclass
class World:
    params: Params
    companies: list[Company]
    buyers: list[Buyer]

    def company(self, deal_id: str) -> Company:
        return next(c for c in self.companies if c.deal_id == deal_id)

    @property
    def aurora(self) -> Company:
        return self.company("deal_aurora")


def _round_to(value: float, step: float) -> float:
    return round(value / step) * step


def _make_company(
    params: Params,
    names: NamePool,
    index: int,
    deal_id: str,
    project: str,
    sector: str,
    suffix: str,
) -> Company:
    rng = rng_for(params.seed, "company", deal_id)
    sec = SECTORS[sector]
    stem = project if deal_id == "deal_aurora" else names.stem()
    names.reserve(stem)
    name = f"{stem} {suffix}"
    anchors = params.seed == DEMO_SEED and deal_id == "deal_aurora"
    fin = generate_financials(
        rng,
        revenue_last=1824 if anchors else None,
        revenue_prev=1680 if anchors else None,
        gross_margin_last=0.385 if anchors else None,
    )
    employees_last = int(fin.revenue[4] / 10 * rng.uniform(4.5, 7.5))
    headcount = [round(employees_last / (1.02 ** (4 - i)) / 10) * 10 for i in range(5)]
    headcount[4] = round(employees_last / 10) * 10
    top = 17.0 if anchors else round(rng.uniform(9.0, 31.0), 1)
    revenue = fin.revenue[4] / 10
    ebitda = fin.ebitda[4] / 10
    net_debt = (fin.total_debt[4] - fin.cash[4]) / 10
    ev = round(ebitda * rng.uniform(8.5, 10.5), 1)
    equity = round(ev - net_debt, 1)
    press_factor = rng.uniform(0.93, 0.975)
    press_revenue = 179.0 if anchors else float(round(revenue * press_factor))
    while abs(press_revenue - revenue) / revenue < 0.012:
        press_factor -= 0.01
        press_revenue = float(round(revenue * press_factor))
    press_ebitda = float(round(ebitda * rng.uniform(1.06, 1.14)))
    hc_press = int(round(headcount[4] * rng.uniform(0.90, 0.94) / 10) * 10)
    dist_stem = stem[:-1] + ("e" if not stem.endswith("e") else "a")
    distractor = f"{dist_stem} {suffix}"
    restated = (
        None
        if deal_id == "deal_aurora" or rng.random() >= params.hard_negative_rate
        else round(fin.revenue[3] / 10 * 0.988, 1)
    )
    return Company(
        deal_id=deal_id,
        project=project,
        key=stem.lower(),
        name=name,
        legal=f"{name} GmbH",
        sector=sector,
        hq=CITIES[index % len(CITIES)],
        ceo=names.person(),
        cfo=names.person(),
        founded=rng.randrange(1950, 2005),
        fin=fin,
        headcount=headcount,
        plants=rng.randrange(3, 9),
        backlog=round(revenue * rng.uniform(0.25, 0.6), 1),
        top_customer=top,
        top10=round(min(95.0, top + rng.uniform(22.0, 35.0)), 1),
        export_share_old=round(rng.uniform(35.0, 72.0), 1),
        plants_old=rng.randrange(2, 8),
        distractor=distractor,
        distractor_revenue=round(revenue * rng.uniform(0.93, 1.07), 1),
        ev=ev,
        equity=equity,
        draft_ev=round(ev * rng.uniform(0.94, 0.97), 1),
        press_revenue=press_revenue,
        press_ebitda=press_ebitda,
        press_headcount=hc_press,
        orig_pr_ebitda=round(ebitda * rng.uniform(1.08, 1.16), 1),
        restated_prior_revenue=restated,
        products=list(sec.products),
        customers=list(sec.customers),
        sector_label=sec.label,
        site=sec.site,
    )


def _date_between(rng: Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randrange((end - start).days))


def _make_buyers(params: Params, names: NamePool, aurora: Company) -> list[Buyer]:
    rng = rng_for(params.seed, "buyers")
    buyers: list[Buyer] = []
    ev, equity = aurora.ev, aurora.equity
    # planned groups, spread over the 20 buyers of each type
    ratio_plan = [0.72, 0.66, 0.68, 0.48, 0.45, 0.52] + [
        0.1,
        0.14,
        0.18,
        0.22,
        0.26,
        0.3,
        0.12,
        0.16,
        0.2,
        0.24,
        0.28,
        0.32,
        0.08,
        0.34,
    ]
    share_plan = [0.015, 0.02, 0.03, 0.035, 0.012, 0.55, 0.65, 0.8] + [
        0.07,
        0.09,
        0.11,
        0.13,
        0.15,
        0.17,
        0.19,
        0.21,
        0.23,
        0.26,
        0.29,
        0.32,
    ]
    rng.shuffle(ratio_plan)
    rng.shuffle(share_plan)
    sector_pool = SECTOR_KEYS
    for n in range(1, 41):
        strategic = n % 2 == 1
        k = (n - 1) // 2
        stem = names.stem()
        if strategic:
            name = f"{stem} {rng.choice(['Industries', 'Group', 'Holdings', 'Systems'])}"
        else:
            name = (
                f"{stem} {rng.choice(['Capital Partners', 'Equity', 'Investments', 'Growth Fund'])}"
            )
        sectors = rng.sample(sector_pool, rng.choice([1, 2, 2, 3]))
        if rng.random() < 0.5 and AURORA_SECTOR not in sectors:
            sectors[0] = AURORA_SECTOR
        geos = rng.sample(GEOGRAPHIES, rng.choice([1, 2, 2, 3]))
        if rng.random() < 0.55 and AURORA_REGION not in geos:
            geos[0] = AURORA_REGION
        listed = rng.random() < (0.85 if strategic else 0.15)
        if strategic:
            size = max(150.0, _round_to(ev / ratio_plan[k], 50))
            ticket_min = ticket_max = vintage = None
        else:
            size = max(100.0, _round_to(equity / share_plan[k], 50))
            ticket_min = max(5.0, _round_to(size * rng.uniform(0.03, 0.06), 5))
            ticket_max = max(ticket_min + 5, _round_to(size * rng.uniform(0.10, 0.20), 5))
            vintage = None if listed else rng.randrange(2016, 2024)
        investment_end = (vintage + rng.choice([5, 6])) if vintage is not None else None
        end_stated = investment_end is not None and rng.random() < 0.7
        share_stated = strategic and rng.random() < 0.6
        market_share = round(rng.uniform(8.0, 52.0), 1) if strategic else None
        reg = rng.random()
        reg_state: RegState = (
            "sovereign"
            if reg < 0.2
            else "defense"
            if reg < 0.28
            else "private"
            if reg < 0.68
            else "unspecified"
        )
        acqs: list[Acquisition] = []
        for _ in range(rng.choice([0, 1, 1, 2, 2, 3]) if strategic else rng.choice([0, 1, 1, 2])):
            sector = AURORA_SECTOR if rng.random() < 0.3 else rng.choice(sector_pool)
            when = _date_between(rng, date(2022, 1, 15), date(2025, 6, 15))
            acqs.append(
                Acquisition(
                    when,
                    sector,
                    f"{names.stem()} {rng.choice(['Works', 'Tech', 'Systems', 'Partners'])}",
                )
            )
        acqs.sort(key=lambda a: a.when, reverse=True)
        profile = BuyerProfile(
            id=f"buyer_{n:02d}",
            name=name,
            buyer_type=BuyerType.STRATEGIC if strategic else BuyerType.FINANCIAL,
            sectors=sectors,
            geographies=geos,
            size_eur_m=size,
            ticket_min_eur_m=ticket_min,
            ticket_max_eur_m=ticket_max,
            fund_vintage_year=vintage,
            listed=listed,
        )
        conflict = n % 3 != 0 and n <= 28  # 14 conflicting buyers among the first 28
        article_conflict = (
            float(max(100.0, _round_to(size * rng.uniform(0.82, 0.92), 10))) if conflict else None
        )
        buyers.append(
            Buyer(
                profile=profile,
                investment_end=investment_end,
                end_stated=end_stated,
                market_share=market_share,
                share_stated=share_stated,
                reg_state=reg_state,
                acquisitions=acqs,
                revenue=round(size * rng.uniform(0.2, 0.9), 1),
                employees=int(rng.uniform(800, 25000) // 10 * 10),
                portfolio=rng.randrange(6, 24),
                article_conflict=article_conflict,
                old_pr=((not strategic and n <= 24) or n in (33, 35)) and n not in (7, 22),
                old_filing=strategic and n in (1, 5, 9, 13, 17),
                withdrawn_pr=n in (7, 22),
                aum_old=float(_round_to(size * rng.uniform(0.7, 0.9), 10)),
                employees_old=int(rng.uniform(700, 20000) // 10 * 10),
                extra_article=rng.random() < 0.5,
                reg_in_profile=rng.random() < 0.5,
            )
        )
    return buyers


def build_world(params: Params) -> World:
    names = NamePool(rng_for(params.seed, "names"))
    companies = [
        _make_company(params, names, i, d, p, s, suf) for i, (d, p, s, suf) in enumerate(DEAL_PLAN)
    ]
    aurora = companies[0]
    buyers = _make_buyers(params, names, aurora)
    return World(params=params, companies=companies, buyers=buyers)


# ---- truth rules for buyer criteria (documented in docs/DATASET_CARD.md) --------------------


def months_between(later: date, earlier: date) -> float:
    return (later - earlier).days / 30.4375


def share_of_fund(equity: float, size: float) -> float:
    return equity / size


def buyer_criteria(buyer: Buyer, aurora: Company) -> dict[str, str]:
    """Criterion key -> status (met, not_met, unknown) for the Aurora screening."""
    p = buyer.profile
    out: dict[str, str] = {}
    out["sector_focus"] = "met" if AURORA_SECTOR in p.sectors else "not_met"
    out["geography"] = "met" if AURORA_REGION in p.geographies else "not_met"
    low, high = aurora.ev, aurora.ev * 60
    out["size_range"] = "met" if low <= p.size_eur_m <= high else "not_met"
    out["regulatory_fdi"] = {
        "sovereign": "not_met",
        "defense": "not_met",
        "private": "met",
        "unspecified": "unknown",
    }[buyer.reg_state]
    acqs = buyer.acquisitions
    if not acqs:
        out["recent_activity"] = "unknown"
    else:
        recent = [a for a in acqs if months_between(REFERENCE_DATE, a.when) <= 36]
        similar = [a for a in recent if a.sector == AURORA_SECTOR]
        out["recent_activity"] = "met" if similar else "not_met"
    if buyer.profile.buyer_type is BuyerType.FINANCIAL:
        share = share_of_fund(aurora.equity, p.size_eur_m)
        out["ticket_fit"] = "met" if 0.05 <= share <= 0.40 else "not_met"
        if p.listed:
            out["fund_lifecycle"] = "met"
        elif buyer.end_stated and buyer.investment_end is not None:
            out["fund_lifecycle"] = (
                "met" if buyer.investment_end - REFERENCE_DATE.year >= 2 else "not_met"
            )
        else:
            out["fund_lifecycle"] = "unknown"
        out["antitrust"] = "unknown"
    else:
        ratio = aurora.ev / p.size_eur_m
        out["ev_ratio"] = "not_met" if ratio > 0.60 else "met"
        if not acqs:
            out["integration_bandwidth"] = "unknown"
        else:
            n24 = sum(1 for a in acqs if months_between(REFERENCE_DATE, a.when) <= 24)
            out["integration_bandwidth"] = "met" if n24 <= 2 else "not_met"
        if buyer.share_stated and buyer.market_share is not None:
            out["antitrust"] = "not_met" if buyer.market_share >= 35.0 else "met"
        else:
            out["antitrust"] = "unknown"
    return out
