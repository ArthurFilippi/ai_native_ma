"""Neutral prose around the planted facts: combinatorial sentences without numbers.

The sentences never mention the topics of the unanswerable questions (see `absent.py`), so those
questions stay genuinely unanswerable. The generator is templated on purpose (a documented bias).
"""

from __future__ import annotations

from random import Random

SUBJECTS = [
    "{C}", "The company", "The group", "Management", "The business", "The leadership team",
    "The operating team", "The board",
]
VERBS = [
    "focuses on", "continues to invest in", "has built a reputation for", "relies on",
    "benefits from", "is expanding its work on", "keeps a close eye on", "has refined its approach to",
    "pays particular attention to", "has developed expertise in", "maintains strong relationships around",
    "regularly reviews",
]
TAILS = [
    "", "", " across its core markets", " in line with its long term plan",
    " as part of its established way of working", " with support from experienced teams",
    " throughout the organisation", " where it sees durable demand", " with a pragmatic mindset",
]
THEMES: dict[str, list[str]] = {
    "overview": [
        "the quality of its {p1} and {p2}", "long standing relationships with {cust}",
        "a disciplined approach to product development", "its position in {sector} in {region}",
        "reliable delivery and consistent service", "the trust of its established customer base",
        "continuous improvement of its {p3}", "a clear division of responsibilities between teams",
    ],
    "products": [
        "its range of {p1}", "the engineering of its {p2}", "the roadmap for its {p3}",
        "service and spare supply for its {p4}", "customer specific variants of its {p1}",
        "testing and validation of its {p2}", "documentation that accompanies its {p3}",
        "modular design across its {p4}",
    ],
    "markets": [
        "demand from {cust}", "the competitive landscape in {sector}", "regional preferences in {region}",
        "pricing discipline against competing suppliers", "channel partners that serve {cust}",
        "customer procurement cycles", "the replacement cycle of installed products",
        "regulatory standards that apply to {sector}",
    ],
    "customers": [
        "framework agreements with {cust}", "joint development with key accounts",
        "service levels agreed with {cust}", "a broad base of repeat buyers", "onboarding of new accounts",
        "feedback collected from {cust}", "contract renewals with long standing partners",
        "after sales support for {cust}",
    ],
    "operations": [
        "the layout of its {site}s", "supplier qualification and audits", "maintenance of its machinery",
        "planning of production capacity", "quality control at each {site}",
        "logistics between its {site}s and customers", "continuous training of operators",
        "procurement of raw materials from approved suppliers",
    ],
    "people": [
        "the development of its skilled workforce", "apprenticeship programmes near {hq}",
        "safety routines on the shop floor", "internal promotion into leadership roles",
        "cooperation with local technical schools", "regular dialogue with employee representatives",
    ],
    "strategy": [
        "selective investment in automation", "the extension of its aftermarket offering",
        "a measured expansion in neighbouring regions", "closer integration with key accounts",
        "the renewal of its digital tools", "targeted add-on opportunities in {sector}",
        "working capital discipline", "the simplification of its product portfolio",
    ],
    "risks": [
        "the cyclical nature of demand from {cust}", "the availability of qualified staff",
        "supplier concentration for selected inputs", "currency movements in export markets",
        "changes in customer ordering patterns", "the pace of technological change in {sector}",
        "the integration of new systems", "the continuity of key management",
    ],
    "process": [
        "a structured data room with controlled access", "management meetings with qualified bidders",
        "a clear timetable for indicative offers", "confidentiality undertakings for all participants",
        "site visits arranged through the advisers", "a single point of contact for questions",
    ],
    "governance": [
        "the reporting lines between management and the board", "internal controls over financial reporting",
        "the approval of larger investments by the board", "the review of strategy at regular meetings",
        "risk reviews prepared by the finance team", "the monitoring of key operating indicators",
    ],
}


def sentence(rng: Random, theme: str, ctx: dict[str, str]) -> str:
    subject = rng.choice(SUBJECTS)
    verb = rng.choice(VERBS)
    obj = rng.choice(THEMES[theme])
    tail = rng.choice(TAILS)
    text = f"{subject} {verb} {obj}{tail}."
    text = text.format(**ctx)
    return text[0].upper() + text[1:]


def paragraph(rng: Random, theme: str, ctx: dict[str, str], n: int = 4) -> str:
    seen: set[str] = set()
    out: list[str] = []
    guard = 0
    while len(out) < n and guard < 50:
        guard += 1
        s = sentence(rng, theme, ctx)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return " ".join(out)


def context(company_name: str, sector_label: str, products: list[str], customers: list[str],
            site: str, hq: str, region: str) -> dict[str, str]:
    return {
        "C": company_name,
        "sector": sector_label,
        "region": region,
        "hq": hq,
        "site": site,
        "cust": customers[0] if len(customers) == 1 else f"{customers[0]} and {customers[1]}",
        "p1": products[0],
        "p2": products[1],
        "p3": products[2],
        "p4": products[3],
    }
