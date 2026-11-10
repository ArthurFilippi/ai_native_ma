# ruff: noqa: E501
"""Documents of the deal data rooms: CIM, management presentation, model, agreements, press."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from random import Random

from ainma.contracts import DocStatus, DocType
from ainma.synth import filler
from ainma.synth.builder import DocWriter, FactBook
from ainma.synth.common import YEARS, Params, rng_for
from ainma.synth.docspec import DocSpec, Part
from ainma.synth.finance import tenths
from ainma.synth.world import AURORA_REGION, Company

MARK = "SYNTHETIC DOCUMENT, fictional data."

LEGAL = [
    "The seller shall deliver all documents listed in the schedule on the closing date.",
    "Each party shall bear its own costs in connection with this agreement.",
    "Notices under this agreement shall be given in writing to the addresses of the parties.",
    "The buyer shall be entitled to rely on the statements made by the seller in the schedule.",
    "No party may assign its rights under this agreement without the written consent of the other.",
    "The parties shall cooperate in good faith to complete the transaction in accordance with the timetable.",
    "Any amendment to this agreement requires the written form and the signature of all parties.",
    "If a provision is held to be invalid, the remaining provisions shall continue in force.",
    "The seller shall conduct the business in the ordinary course until the closing date.",
    "The parties shall keep the terms of this agreement confidential.",
    "Disputes shall be settled by arbitration under the rules chosen by the parties.",
    "The conditions to closing are listed in the schedule and may be waived only by the party they protect.",
]


@dataclass
class Ctx:
    comp: Company
    book: FactBook
    params: Params
    region: str = AURORA_REGION

    def doc(
        self,
        doc_id: str,
        folder: str,
        fmt: str,
        title: str,
        doc_type: DocType,
        published: date,
        *,
        status: DocStatus = DocStatus.CURRENT,
        superseded_by: str | None = None,
    ) -> tuple[DocSpec, DocWriter, Random]:
        spec = DocSpec(
            id=doc_id,
            folder=folder,
            fmt=fmt,  # type: ignore[arg-type]
            title=title,
            doc_type=doc_type,
            published_on=published,
            deal_id=self.comp.deal_id,
            status=status,
            superseded_by=superseded_by,
        )
        rng = rng_for(self.params.seed, "doc", doc_id)
        return spec, DocWriter(spec, self.book, rng, self.params), rng

    def fctx(self) -> dict[str, str]:
        c = self.comp
        return filler.context(c.name, c.sector_label, c.products, c.customers, c.site, c.hq, self.region)

    @property
    def folder(self) -> str:
        return self.comp.deal_id


def _intro(spec: DocSpec, title: str, extra: str = "") -> None:
    spec.heading(title)
    spec.para(f"{MARK} {extra}".strip())


def _filler(spec: DocSpec, rng: Random, ctx: Ctx, theme: str, paragraphs: int = 2, n: int = 4) -> None:
    for _ in range(paragraphs):
        spec.para(filler.paragraph(rng, theme, ctx.fctx(), n))


# ---- CIM ----------------------------------------------------------------------------------


def build_cim(ctx: Ctx, doc_id: str, published: date, *, big: bool) -> DocSpec:
    c = ctx.comp
    spec, w, rng = ctx.doc(
        doc_id, ctx.folder, "pdf", f"Project {c.project}, Confidential Information Memorandum",
        DocType.DEAL_DOCUMENT, published,
    )
    fin = c.fin
    last, prev = "FY2024", "FY2023"
    name = c.name

    def table_pl() -> None:
        w.fact_table(
            name, ["EUR m", *YEARS],
            [
                ("Revenue", "revenue", tenths(fin.revenue)),
                ("Gross profit", None, tenths(fin.gross_profit)),
                ("EBITDA", "ebitda", tenths(fin.ebitda)),
                ("EBIT", None, tenths(fin.ebit)),
                ("Net income", None, tenths(fin.net_income)),
            ],
            YEARS,
        )

    def financial() -> None:
        spec.para(
            w.stated(name, "revenue", last, c.revenue_last, form="lit", prev=fin.revenue[3] / 10, force=0, style="mn"),
            w.stated(name, "ebitda", last, c.ebitda_last, prev=fin.ebitda[3] / 10, force=0, form="lit", style="mn"),
        )
        spec.para(
            w.stated(name, "gross_margin", last, c.gross_margin_last),
            w.stated(name, "ebitda_margin", last, c.margin(fin.ebitda, 4)),
        )
        spec.para(w.footnote(name, "revenue", last, c.revenue_last, 1))
        _filler(spec, rng, ctx, "overview", 2)

    def customers() -> None:
        spec.para(
            w.stated(name, "top_customer_share", last, c.top_customer),
            w.stated(name, "top10_customer_share", last, c.top10),
        )
        _filler(spec, rng, ctx, "customers", 3)

    def operations() -> None:
        spec.para(w.stated(name, "order_backlog", last, c.backlog), w.stated(name, "plants", last, float(c.plants)))
        _filler(spec, rng, ctx, "operations", 3)

    def exec_summary() -> None:
        spec.para(
            w.stated(name, "headcount", last, float(c.headcount[4])),
            w.stated(name, "plants", last, float(c.plants), form="par"),
        )
        spec.para(
            f"{name} is a {c.sector_label} company headquartered in {c.hq}, in {ctx.region}.",
            f"It was founded in {c.founded}.",
        )
        _filler(spec, rng, ctx, "overview", 3)

    def transaction() -> None:
        spec.para(
            w.stated(name, "enterprise_value", "static", c.ev),
            w.stated(name, "equity_value", "static", c.equity),
        )
        _filler(spec, rng, ctx, "process", 2)

    _intro(spec, f"Project {c.project}", "Confidential Information Memorandum. Prepared by the sell-side advisers.")
    spec.para(f"Subject: {name}, {c.hq}. Dated {published.isoformat()}.")
    spec.page_break()
    if big:
        spec.heading("Important notice")
        spec.para("This memorandum has been prepared for qualified bidders who signed a confidentiality undertaking.")
        spec.para("The information is fictional and provided for evaluation purposes only. No representation is made as to its completeness.")
        _filler(spec, rng, ctx, "process", 2)
        spec.page_break()
        spec.heading("Contents")
        spec.para("1. Executive summary. 2. Investment highlights. 3. Company history. 4. Products, part one. 5. Products, part two. 6. Market overview. 7. Competitive position. 8. Customers. 9. Financial overview. 10. Income statement. 11. Balance sheet. 12. Cash flow. 13. Operations. 14. People and organisation. 15. Governance. 16. Strategy. 17. Outlook. 18. Risk factors. 19. Transaction overview. 20. Sale process. 21. Glossary.")
        spec.page_break()
        plan = [
            ("1. Executive summary", exec_summary),
            ("2. Investment highlights", lambda: _filler(spec, rng, ctx, "overview", 4)),
            ("3. Company history", lambda: _filler(spec, rng, ctx, "overview", 4)),
            ("4. Products, part one", lambda: _filler(spec, rng, ctx, "products", 4)),
            ("5. Products, part two", lambda: _filler(spec, rng, ctx, "products", 4)),
            ("6. Market overview", lambda: _filler(spec, rng, ctx, "markets", 4)),
            ("7. Competitive position", lambda: _filler(spec, rng, ctx, "markets", 4)),
            ("8. Customers", customers),
            ("9. Financial overview", financial),
            ("10. Income statement", lambda: (table_pl(), _filler(spec, rng, ctx, "governance", 1))),
            ("11. Balance sheet", lambda: _balance(spec, w, ctx, rng)),
            ("12. Cash flow", lambda: _cashflow(spec, w, ctx, rng)),
            ("13. Operations", operations),
            ("14. People and organisation", lambda: _filler(spec, rng, ctx, "people", 4)),
            ("15. Governance", lambda: _filler(spec, rng, ctx, "governance", 4)),
            ("16. Strategy", lambda: _filler(spec, rng, ctx, "strategy", 4)),
            ("17. Outlook", lambda: _filler(spec, rng, ctx, "strategy", 4)),
            ("18. Risk factors", lambda: _filler(spec, rng, ctx, "risks", 4)),
            ("19. Transaction overview", transaction),
            ("20. Sale process", lambda: _filler(spec, rng, ctx, "process", 4)),
            ("21. Glossary", lambda: spec.para("EBITDA means earnings before interest, tax, depreciation and amortisation. A bidder is a party that submits an offer. The data room is the secure repository of documents.")),
        ]
    else:
        plan = [
            ("1. Executive summary", exec_summary),
            ("2. Business overview", lambda: _filler(spec, rng, ctx, "products", 3)),
            ("3. Customers", customers),
            ("4. Operations", operations),
            ("5. Financial overview", lambda: (financial(), table_pl())),
            ("6. Transaction overview", transaction),
        ]
    for index, (title, body) in enumerate(plan):
        spec.heading(title)
        body()
        if index < len(plan) - 1:
            spec.page_break()
    return spec


def _balance(spec: DocSpec, w: DocWriter, ctx: Ctx, rng: Random) -> None:
    c = ctx.comp
    fin = c.fin
    spec.para(w.stated(c.name, "net_debt", "FY2024", c.net_debt_last))
    spec.table(
        [
            ["EUR m", *YEARS],
            ["Cash", *tenths(fin.cash)],
            ["Total assets", *tenths(fin.total_assets)],
            ["Total debt", *tenths(fin.total_debt)],
            ["Total equity", *tenths(fin.equity)],
        ]
    )
    _filler(spec, rng, ctx, "governance", 1)


def _cashflow(spec: DocSpec, w: DocWriter, ctx: Ctx, rng: Random) -> None:
    c = ctx.comp
    fin = c.fin
    spec.para(w.stated(c.name, "capex", "FY2024", fin.capex[4] / 10))
    w.fact_table(
        c.name, ["EUR m", *YEARS],
        [("Operating cash flow", None, tenths(fin.ocf)), ("Capital expenditure", "capex", tenths(fin.capex))],
        YEARS,
    )
    _filler(spec, rng, ctx, "governance", 1)


# ---- management presentation ------------------------------------------------------------------


def build_mgmt(ctx: Ctx, doc_id: str, published: date) -> DocSpec:
    c = ctx.comp
    spec, w, rng = ctx.doc(
        doc_id, ctx.folder, "docx", f"Project {c.project}, management presentation",
        DocType.DEAL_DOCUMENT, published,
    )
    name = c.name
    _intro(spec, f"Project {c.project}: management presentation")
    spec.page_break()
    spec.heading("Company snapshot", 2)
    spec.para(w.stated(name, "headcount", "FY2024", float(c.headcount[4]), with_entity=True))
    spec.para(w.stated(name, "plants", "FY2024", float(c.plants), with_entity=True))
    _filler(spec, rng, ctx, "overview", 1)
    spec.page_break()
    spec.heading("Customers", 2)
    spec.para(w.stated(name, "top_customer_share", "FY2024", c.top_customer))
    _filler(spec, rng, ctx, "customers", 1)
    spec.page_break()
    spec.heading("Financial highlights", 2)
    spec.para(w.stated(name, "gross_margin", "FY2024", c.gross_margin_last, with_entity=True))
    if c.restated_prior_revenue is not None:
        text_part = w.stated(name, "revenue", "FY2023", c.restated_prior_revenue, form="lit", force=2, style="mn")
        spec.para(Part("Restated figure: " + text_part.text, text_part.facts))
    _filler(spec, rng, ctx, "strategy", 1)
    return spec


# ---- Aurora only: model, NDA, QoE, board minutes, concentration note ----------------------------


def build_model(ctx: Ctx, doc_id: str, published: date) -> DocSpec:
    c = ctx.comp
    fin = c.fin
    spec, w, _ = ctx.doc(
        doc_id, ctx.folder, "xlsx", f"Project {c.project}, financial model",
        DocType.DEAL_DOCUMENT, published,
    )
    hdr: list[object] = ["EUR m", *YEARS]
    spec.heading("Income Statement")
    w.fact_table(
        c.name, hdr,  # type: ignore[arg-type]
        [
            ("Revenue", "revenue", tenths(fin.revenue)),
            ("Cost of goods sold", None, tenths(fin.cogs)),
            ("Gross profit", None, tenths(fin.gross_profit)),
            ("SG&A", None, tenths(fin.sga)),
            ("EBITDA", "ebitda", tenths(fin.ebitda)),
            ("Depreciation and amortisation", None, tenths(fin.da)),
            ("EBIT", None, tenths(fin.ebit)),
            ("Interest expense", None, tenths(fin.interest)),
            ("Profit before tax", None, tenths(fin.ebt)),
            ("Income tax", None, tenths(fin.tax)),
            ("Net income", None, tenths(fin.net_income)),
        ],
        YEARS,
    )
    spec.heading("Balance Sheet")
    spec.table(
        [
            hdr,  # type: ignore[list-item]
            ["Cash", *tenths(fin.cash)],
            ["Receivables", *tenths(fin.receivables)],
            ["Inventory", *tenths(fin.inventory)],
            ["Current assets", *tenths(fin.current_assets)],
            ["Property, plant and equipment", *tenths(fin.ppe)],
            ["Other non-current assets", *tenths(fin.other_nc)],
            ["Total assets", *tenths(fin.total_assets)],
            ["Payables", *tenths(fin.payables)],
            ["Other current liabilities", *tenths(fin.other_cl)],
            ["Short-term debt", *tenths(fin.st_debt)],
            ["Current liabilities", *tenths(fin.current_liabilities)],
            ["Long-term debt", *tenths(fin.lt_debt)],
            ["Total debt", *tenths(fin.total_debt)],
            ["Total equity", *tenths(fin.equity)],
            ["Total liabilities and equity", *tenths(fin.total_le)],
        ]
    )
    spec.heading("Cash Flow")
    w.fact_table(
        c.name, hdr,  # type: ignore[arg-type]
        [
            ("Net income", None, tenths(fin.net_income)),
            ("Depreciation and amortisation", None, tenths(fin.da)),
            ("Change in working capital", None, tenths(fin.d_wc)),
            ("Operating cash flow", None, tenths(fin.ocf)),
            ("Capital expenditure", "capex", tenths(fin.capex)),
        ],
        YEARS,
    )
    return spec


def build_nda(ctx: Ctx, doc_id: str, published: date) -> DocSpec:
    c = ctx.comp
    spec, w, rng = ctx.doc(
        doc_id, ctx.folder, "pdf", f"Project {c.project}, non-disclosure agreement (signed)",
        DocType.SIGNED_AGREEMENT, published,
    )
    _intro(spec, f"Non-disclosure agreement, Project {c.project}", "Executed copy.")
    spec.para(f"This agreement is made between {c.legal} (the Company) and the bidder named in the signature page.")
    spec.heading("1. Confidential information", 2)
    spec.para("Confidential information means all information about the Company disclosed to the bidder in connection with the transaction.")
    spec.heading("2. Term", 2)
    spec.para(w.stated(f"Project {c.project} NDA", "nda_term_months", "static", 24.0, form="lit", force=1, with_entity=True))
    spec.heading("3. General", 2)
    for text in rng.sample(LEGAL, 5):
        spec.para(text)
    spec.para(f"Signed on {published.isoformat()} by both parties.")
    return spec


def build_qoe(ctx: Ctx, doc_id: str, published: date) -> DocSpec:
    c = ctx.comp
    spec, w, rng = ctx.doc(
        doc_id, ctx.folder, "pdf", f"Project {c.project}, quality of earnings summary",
        DocType.DEAL_DOCUMENT, published,
    )
    _intro(spec, f"Quality of earnings summary, Project {c.project}")
    spec.para(
        w.stated(c.name, "adjusted_ebitda", "FY2024", round(c.ebitda_last * 1.03, 1)),
        w.stated(c.name, "gross_margin", "FY2024", c.gross_margin_last, form="lit", with_entity=True),
    )
    spec.para(w.stated(c.name, "net_debt", "FY2024", c.net_debt_last, with_entity=True))
    spec.para("Adjustments relate to one-off restructuring items and the normalisation of owner related costs.")
    _filler(spec, rng, ctx, "governance", 2)
    return spec


def build_board(ctx: Ctx, doc_id: str, published: date) -> DocSpec:
    c = ctx.comp
    spec, w, rng = ctx.doc(
        doc_id, ctx.folder, "docx", f"Project {c.project}, board minutes",
        DocType.DEAL_DOCUMENT, published,
    )
    _intro(spec, f"Minutes of the board meeting, {c.name}", f"Meeting held on {published.isoformat()}.")
    spec.heading("Item 1: financial update", 2)
    spec.para(w.stated(c.name, "capex", "FY2024", c.fin.capex[4] / 10, with_entity=True))
    spec.para(w.stated(c.name, "ebitda_margin", "FY2024", c.margin(c.fin.ebitda, 4), with_entity=True))
    spec.heading("Item 2: sale process", 2)
    _filler(spec, rng, ctx, "process", 2)
    spec.para("The board resolved to proceed with the sale process and authorised management to open the data room.")
    return spec


def build_concentration(ctx: Ctx, doc_id: str, published: date) -> DocSpec:
    c = ctx.comp
    spec, w, rng = ctx.doc(
        doc_id, ctx.folder, "docx", f"Project {c.project}, customer concentration note",
        DocType.DEAL_DOCUMENT, published,
    )
    _intro(spec, f"Customer concentration note, {c.name}")
    spec.para(
        w.stated(c.name, "top_customer_share", "FY2024", c.top_customer, with_entity=True, form="lit"),
        w.stated(c.name, "top10_customer_share", "FY2024", c.top10, with_entity=True, form="lit"),
    )
    _filler(spec, rng, ctx, "customers", 2)
    return spec


# ---- agreements and press ---------------------------------------------------------------------


def build_spa(ctx: Ctx, doc_id: str, published: date, *, draft: bool, superseded_by: str | None = None) -> DocSpec:
    c = ctx.comp
    kind = "draft" if draft else "executed"
    spec, w, rng = ctx.doc(
        doc_id, ctx.folder, "pdf", f"Project {c.project}, share purchase agreement ({kind})",
        DocType.DEAL_DOCUMENT if draft else DocType.SIGNED_AGREEMENT, published,
        status=DocStatus.SUPERSEDED if draft else DocStatus.CURRENT, superseded_by=superseded_by,
    )
    value = c.draft_ev if draft else c.ev
    _intro(spec, f"Share purchase agreement, Project {c.project}", "Draft for discussion." if draft else "Executed version.")
    spec.para(f"This share purchase agreement relates to the shares in {c.legal}.")
    spec.heading("1. Purchase price", 2)
    spec.para(w.stated(c.name, "enterprise_value", "static", value, with_entity=True, form="lit", force=1))
    spec.heading("2. Undertakings", 2)
    for text in rng.sample(LEGAL, 6):
        spec.para(text)
    return spec


def _short(c: Company) -> str:
    return c.name.split(" ")[0]


def build_article(
    ctx: Ctx, doc_id: str, published: date, *, aurora: bool, extra_net_debt: bool = False
) -> DocSpec:
    c = ctx.comp
    short = _short(c)
    spec, w, rng = ctx.doc(
        doc_id, ctx.folder, "txt", f"Trade press: {short} prepares for a sale", DocType.PRESS_ARTICLE, published
    )
    _intro(spec, f"{short} prepares for a sale")
    spec.para(f"{short}, a {c.sector_label} company based in {c.hq}, is preparing a sale process, according to people familiar with the matter.")
    anchor = 0 if aurora else None
    spec.para(
        w.press(c.name, short, "revenue", "FY2024", c.press_revenue, force=anchor),
        w.press(c.name, short, "ebitda", "FY2024", c.press_ebitda),
    )
    spec.para(w.press(c.name, short, "headcount", "FY2024", float(c.press_headcount)))
    if ctx.params.hard_negative_rate > rng.random():
        spec.para(
            f"Not to be confused with {c.distractor}, a separate company.",
            w.stated(c.distractor, "revenue", "FY2024", c.distractor_revenue, form="lit", force=1, with_entity=True, style="mn"),
        )
    spec.para(filler.paragraph(rng, "markets", ctx.fctx(), 2))
    return spec


def build_article2(ctx: Ctx, doc_id: str, published: date) -> DocSpec:
    c = ctx.comp
    short = _short(c)
    spec, w, rng = ctx.doc(
        doc_id, ctx.folder, "txt", f"Trade press: {short} balance sheet in focus", DocType.PRESS_ARTICLE, published
    )
    _intro(spec, f"{short} balance sheet in focus")
    spec.para(w.stated(c.name, "net_debt", "FY2024", c.net_debt_last, with_entity=True, form="lit", force=1))
    spec.para(filler.paragraph(rng, "strategy", ctx.fctx(), 3))
    return spec


def build_pr(ctx: Ctx, doc_id: str, published: date) -> DocSpec:
    c = ctx.comp
    spec, w, rng = ctx.doc(
        doc_id, ctx.folder, "txt", f"{c.name} reports order backlog", DocType.PRESS_RELEASE, published
    )
    _intro(spec, f"{c.name} reports order backlog")
    spec.para(w.stated(c.name, "order_backlog", "FY2024", c.backlog, with_entity=True))
    spec.para(filler.paragraph(rng, "customers", ctx.fctx(), 2))
    return spec


def build_pr_pair(
    ctx: Ctx, orig_id: str, corr_id: str, orig_date: date, corr_date: date
) -> tuple[DocSpec, DocSpec]:
    c = ctx.comp
    orig, w1, rng = ctx.doc(
        orig_id, ctx.folder, "txt", f"{c.name} reports results (original, withdrawn)",
        DocType.PRESS_RELEASE, orig_date, status=DocStatus.WITHDRAWN, superseded_by=corr_id,
    )
    _intro(orig, f"{c.name} reports results")
    orig.para(w1.stated(c.name, "ebitda", "FY2024", c.orig_pr_ebitda, with_entity=True, form="lit", force=1, style="mn"))
    orig.para(filler.paragraph(rng, "overview", ctx.fctx(), 2))
    corr, w2, rng2 = ctx.doc(
        corr_id, ctx.folder, "txt", f"{c.name} corrects results release", DocType.PRESS_RELEASE, corr_date
    )
    _intro(corr, f"{c.name} corrects results release")
    corr.para(f"This release corrects the release of {orig_date.isoformat()}, which is withdrawn.")
    corr.para(w2.stated(c.name, "ebitda", "FY2024", c.ebitda_last, with_entity=True, form="lit", force=1, style="mn"))
    corr.para(filler.paragraph(rng2, "overview", ctx.fctx(), 2))
    return orig, corr


def build_old_article(ctx: Ctx, doc_id: str, published: date) -> DocSpec:
    c = ctx.comp
    short = _short(c)
    spec, w, rng = ctx.doc(
        doc_id, ctx.folder, "txt", f"Trade press: {short} export strategy", DocType.PRESS_ARTICLE, published
    )
    _intro(spec, f"{short} export strategy")
    spec.para(w.stated(c.name, "export_share", "FY2023", c.export_share_old, with_entity=True, form="lit", force=1))
    spec.para(filler.paragraph(rng, "markets", ctx.fctx(), 2))
    return spec


def build_old_deck(ctx: Ctx, doc_id: str, published: date) -> DocSpec:
    c = ctx.comp
    spec, w, rng = ctx.doc(
        doc_id, ctx.folder, "docx", f"Project {c.project}, prior-year management presentation",
        DocType.DEAL_DOCUMENT, published,
    )
    _intro(spec, f"Prior-year management presentation, {c.name}")
    spec.para(w.stated(c.name, "plants", "FY2022", float(c.plants_old), with_entity=True, form="lit", force=1))
    spec.para(filler.paragraph(rng, "operations", ctx.fctx(), 2))
    return spec


def days(d: date, n: int) -> date:
    return d + timedelta(days=n)
