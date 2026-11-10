# ruff: noqa: E501
"""Buyer universe documents (profile page, annual report or fund summary, press, filings) and news."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ainma.contracts import BuyerType, DocStatus, DocType
from ainma.synth import filler
from ainma.synth.builder import DocWriter, FactBook
from ainma.synth.common import REFERENCE_DATE, Params, rng_for
from ainma.synth.docs_company import MARK, days
from ainma.synth.docspec import DocSpec, Fmt
from ainma.synth.truthio import NewsItem
from ainma.synth.world import SECTORS, Acquisition, Buyer, World

MAX_DOCS = 5

REG_TEXT = {
    "sovereign": "The company is majority owned by a sovereign wealth entity.",
    "defense": "The company has significant exposure to defense contracts.",
    "private": "The company is privately owned and has no state shareholders.",
}


@dataclass
class BuyerDocs:
    docs: list[DocSpec]
    published_acquisitions: set[tuple[str, str]]


def _spec(
    b: Buyer,
    suffix: str,
    fmt: Fmt,
    title: str,
    doc_type: DocType,
    published: date,
    status: DocStatus = DocStatus.CURRENT,
    superseded_by: str | None = None,
) -> DocSpec:
    return DocSpec(
        id=f"doc_{b.profile.id}_{suffix}",
        folder="buyers",
        fmt=fmt,
        title=title,
        doc_type=doc_type,
        published_on=published,
        deal_id=None,
        entity_id=b.profile.id,
        status=status,
        superseded_by=superseded_by,
    )


def _writer(spec: DocSpec, book: FactBook, params: Params) -> DocWriter:
    return DocWriter(spec, book, rng_for(params.seed, "doc", spec.id), params)


def _size_metric(b: Buyer) -> str:
    return "aum" if b.profile.buyer_type is BuyerType.FINANCIAL else "market_cap"


def _sector_labels(b: Buyer) -> str:
    return ", ".join(SECTORS[s].label for s in b.profile.sectors)


def build_buyer_docs(world: World, b: Buyer, book: FactBook) -> BuyerDocs:
    params = world.params
    rng = rng_for(params.seed, "buyerdocs", b.profile.id)
    p = b.profile
    name = p.name
    fin = p.buyer_type is BuyerType.FINANCIAL
    size_metric = _size_metric(b)
    docs: list[DocSpec] = []

    # profile page (web, tier 5)
    d_profile = (
        date(2025, 5, 1) + (date(2025, 6, 10) - date(2025, 5, 1)) * rng.randrange(100) // 100
    )
    prof = _spec(b, "profile", "txt", f"{name}: company profile", DocType.WEB, d_profile)
    w = _writer(prof, book, params)
    prof.heading(f"{name}: company profile")
    prof.para(f"{MARK} Profile page of {name}.")
    prof.para(f"{name} is a {'private equity investor' if fin else 'strategic acquirer'}.")
    prof.para(f"Sector focus: {_sector_labels(b)}. Geographic focus: {', '.join(p.geographies)}.")
    prof.para(w.stated(name, size_metric, "FY2024", p.size_eur_m, with_entity=True))
    if fin:
        assert p.ticket_min_eur_m is not None and p.ticket_max_eur_m is not None
        prof.para(w.ticket(name, p.ticket_min_eur_m, p.ticket_max_eur_m))
        if p.fund_vintage_year is not None:
            prof.para(
                w.stated(
                    name,
                    "fund_vintage_year",
                    "static",
                    float(p.fund_vintage_year),
                    with_entity=True,
                )
            )
    prof.para(
        "The company is listed on a regulated exchange."
        if p.listed
        else "The company is privately held."
    )
    if b.reg_in_profile and b.reg_state in REG_TEXT:
        prof.para(REG_TEXT[b.reg_state])
    docs.append(prof)

    # annual report excerpt or fund summary (company report, tier 2)
    d_report = date(2025, 3, 1) + (date(2025, 4, 30) - date(2025, 3, 1)) * rng.randrange(100) // 100
    if fin:
        rep = _spec(b, "report", "docx", f"{name}: fund summary", DocType.COMPANY_REPORT, d_report)
    else:
        rep = _spec(
            b, "report", "pdf", f"{name}: annual report excerpt", DocType.COMPANY_REPORT, d_report
        )
    w = _writer(rep, book, params)
    rep.heading(f"{name}: {'fund summary' if fin else 'annual report excerpt'}")
    rep.para(f"{MARK} Document of {name}.")
    rep.para(w.stated(name, size_metric, "FY2024", p.size_eur_m, with_entity=True))
    if fin:
        assert p.ticket_min_eur_m is not None and p.ticket_max_eur_m is not None
        rep.para(w.ticket(name, p.ticket_min_eur_m, p.ticket_max_eur_m))
        rep.para(
            w.stated(name, "portfolio_companies", "FY2024", float(b.portfolio), with_entity=True)
        )
        if p.fund_vintage_year is not None:
            rep.para(
                w.stated(
                    name,
                    "fund_vintage_year",
                    "static",
                    float(p.fund_vintage_year),
                    with_entity=True,
                )
            )
        if b.end_stated and b.investment_end is not None:
            rep.para(
                w.stated(
                    name,
                    "investment_period_end_year",
                    "static",
                    float(b.investment_end),
                    with_entity=True,
                )
            )
        elif p.listed:
            rep.para(
                "The vehicle is a permanent capital structure without a fixed investment period."
            )
    else:
        rep.para(w.stated(name, "revenue", "FY2024", b.revenue, with_entity=True))
        rep.para(w.stated(name, "headcount", "FY2024", float(b.employees), with_entity=True))
        if b.share_stated and b.market_share is not None:
            rep.para(w.stated(name, "market_share", "FY2024", b.market_share, with_entity=True))
    if (not b.reg_in_profile) and b.reg_state in REG_TEXT:
        rep.para(REG_TEXT[b.reg_state])
    rep.para(filler.paragraph(rng, "strategy", _ctx(name, p.sectors[0], p.geographies[0]), 2))
    docs.append(rep)

    optional: list[DocSpec] = []
    # conflicting trade article
    if b.article_conflict is not None:
        d_art = (
            date(2025, 2, 1) + (date(2025, 5, 20) - date(2025, 2, 1)) * rng.randrange(100) // 100
        )
        art = _spec(
            b, "article", "txt", f"Trade press: {name} in the market", DocType.PRESS_ARTICLE, d_art
        )
        w = _writer(art, book, params)
        art.heading(f"{name} in the market")
        short = name.split(" ")[0]
        art.para(w.press(name, short, size_metric, "FY2024", b.article_conflict, "int"))
        art.para(filler.paragraph(rng, "markets", _ctx(name, p.sectors[0], p.geographies[0]), 2))
        optional.append(art)
    if b.old_pr:
        d_old = (
            date(2023, 1, 10) + (date(2023, 10, 30) - date(2023, 1, 10)) * rng.randrange(100) // 100
        )
        old = _spec(
            b, "pr_old", "txt", f"{name} announces its position", DocType.PRESS_RELEASE, d_old
        )
        w = _writer(old, book, params)
        old.heading(f"{name} announces its position")
        old.para(
            w.stated(
                name,
                size_metric,
                "FY2022",
                b.aum_old,
                with_entity=True,
                form="lit",
                force=0 if size_metric == "market_cap" else 1,
            )
        )
        old.para(filler.paragraph(rng, "overview", _ctx(name, p.sectors[0], p.geographies[0]), 2))
        optional.append(old)
    if b.old_filing:
        d_fil = (
            date(2022, 3, 1) + (date(2022, 11, 30) - date(2022, 3, 1)) * rng.randrange(100) // 100
        )
        fil = _spec(
            b, "filing", "pdf", f"{name}: annual filing excerpt", DocType.REGULATORY_FILING, d_fil
        )
        w = _writer(fil, book, params)
        fil.heading(f"{name}: annual filing excerpt")
        fil.para(f"{MARK} Filing excerpt of {name}.")
        fil.para(
            w.stated(
                name,
                "headcount",
                "FY2021",
                float(b.employees_old),
                with_entity=True,
                form="lit",
                force=0,
            )
        )
        optional.append(fil)
    if b.withdrawn_pr:
        d_o = date(2025, 4, 2) + (date(2025, 5, 2) - date(2025, 4, 2)) * rng.randrange(100) // 100
        orig = _spec(
            b,
            "pr_orig",
            "txt",
            f"{name} reports its position (original, withdrawn)",
            DocType.PRESS_RELEASE,
            d_o,
            status=DocStatus.WITHDRAWN,
            superseded_by=f"doc_{p.id}_pr_corr",
        )
        w = _writer(orig, book, params)
        orig.heading(f"{name} reports its position")
        wrong = round(p.size_eur_m * 1.12 / 10) * 10.0
        orig.para(
            w.stated(
                name,
                size_metric,
                "FY2024",
                wrong,
                with_entity=True,
                form="lit",
                force=0,
                style="mn",
            )
        )
        corr = _spec(
            b,
            "pr_corr",
            "txt",
            f"{name} corrects its position release",
            DocType.PRESS_RELEASE,
            days(d_o, 4),
        )
        w = _writer(corr, book, params)
        corr.heading(f"{name} corrects its position release")
        corr.para(f"This release corrects the release of {d_o.isoformat()}, which is withdrawn.")
        corr.para(
            w.stated(
                name,
                size_metric,
                "FY2024",
                p.size_eur_m,
                with_entity=True,
                form="lit",
                force=0,
                style="mn",
            )
        )
        optional.extend([orig, corr])
    if b.extra_article and len(docs) + len(optional) < MAX_DOCS - 1:
        d_x = (
            date(2025, 1, 15) + (date(2025, 5, 25) - date(2025, 1, 15)) * rng.randrange(100) // 100
        )
        xa = _spec(
            b, "news", "txt", f"Trade press: what {name} looks for", DocType.PRESS_ARTICLE, d_x
        )
        xa.heading(f"What {name} looks for")
        xa.para(filler.paragraph(rng, "markets", _ctx(name, p.sectors[0], p.geographies[0]), 3))
        optional.append(xa)
    docs.extend(optional)

    published: set[tuple[str, str]] = set()
    room = MAX_DOCS - len(docs)
    for acq in sorted(b.acquisitions, key=lambda a: a.when, reverse=True):
        if room <= 0 or len(published) >= 2:
            break
        pr = _spec(
            b,
            f"pr_{len(published) + 1}",
            "txt",
            f"{name} announces an acquisition",
            DocType.PRESS_RELEASE,
            acq.when,
        )
        pr.heading(f"{name} announces an acquisition")
        pr.para(
            f"{name} announces the acquisition of {acq.target}, a {SECTORS[acq.sector].label} company."
        )
        pr.para(filler.paragraph(rng, "strategy", _ctx(name, acq.sector, p.geographies[0]), 2))
        docs.append(pr)
        published.add((p.id, acq.target))
        room -= 1
    while len(docs) < 3:
        xa = _spec(
            b,
            "news",
            "txt",
            f"Trade press: what {name} looks for",
            DocType.PRESS_ARTICLE,
            date(2025, 2, 20),
        )
        xa.heading(f"What {name} looks for")
        xa.para(filler.paragraph(rng, "markets", _ctx(name, p.sectors[0], p.geographies[0]), 3))
        docs.append(xa)
    return BuyerDocs(docs, published)


def _ctx(name: str, sector: str, region: str) -> dict[str, str]:
    sec = SECTORS[sector]
    return filler.context(name, sec.label, sec.products, sec.customers, sec.site, region, region)


def build_news(world: World, published: set[tuple[str, str]]) -> list[NewsItem]:
    """60 dated simulated items: unpublished acquisitions first, then market commentary."""
    rng = rng_for(world.params.seed, "news")
    items: list[NewsItem] = []
    for b in world.buyers:
        for acq in b.acquisitions:
            if (b.profile.id, acq.target) in published:
                continue
            items.append(_acq_item(b, acq))
    items.sort(key=lambda i: (i.published_on or REFERENCE_DATE, i.entity))
    aurora = world.aurora
    topics = [
        f"Demand for {aurora.sector_label} stays firm in the first half",
        f"{aurora.name} draws interest from several bidders",
        f"Suppliers of {aurora.sector_label} report steady order books",
        f"Sector advisers expect more activity in {aurora.sector_label}",
        f"{aurora.name} management meets qualified bidders",
    ]
    n = 0
    pad: list[NewsItem] = []
    while len(items) + len(pad) < 60:
        deal = world.companies[n % len(world.companies)]
        topic = (
            topics[n % len(topics)]
            if deal.deal_id == "deal_aurora"
            else (
                f"{deal.name} prepares its data room"
                if n % 2
                else f"Investors weigh interest in {deal.sector_label}"
            )
        )
        when = date(2025, 1, 6) + (date(2025, 6, 20) - date(2025, 1, 6)) * rng.randrange(100) // 100
        pad.append(
            NewsItem(
                connector="simulated-news",
                retrieved_on=REFERENCE_DATE,
                title=topic,
                url=None,
                published_on=when,
                doc_type=DocType.PRESS_ARTICLE,
                text=f"{MARK} {topic}. "
                + filler.paragraph(
                    rng,
                    "markets",
                    filler.context(
                        deal.name,
                        deal.sector_label,
                        deal.products,
                        deal.customers,
                        deal.site,
                        deal.hq,
                        "Central Europe",
                    ),
                    3,
                ),
                simulated=True,
                entity=deal.deal_id,
            )
        )
        n += 1
    out = items + pad
    out = out[:60]
    out.sort(key=lambda i: (i.published_on or REFERENCE_DATE, i.entity, i.title))
    return out


def _acq_item(b: Buyer, acq: Acquisition) -> NewsItem:
    title = f"{b.profile.name} completes acquisition of {acq.target}"
    return NewsItem(
        connector="simulated-news",
        retrieved_on=REFERENCE_DATE,
        title=title,
        url=None,
        published_on=acq.when,
        doc_type=DocType.PRESS_ARTICLE,
        text=f"{MARK} {title}. The target is a {SECTORS[acq.sector].label} company.",
        simulated=True,
        entity=b.profile.id,
    )
