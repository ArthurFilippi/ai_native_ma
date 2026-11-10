# ruff: noqa: E501
"""General knowledge layer: about 30 internal reference documents (deal_id null)."""

from __future__ import annotations

from datetime import date

from ainma.contracts import DocType
from ainma.synth import filler
from ainma.synth.builder import DocWriter, FactBook
from ainma.synth.common import Params, rng_for
from ainma.synth.docs_company import MARK
from ainma.synth.docspec import DocSpec, Fmt
from ainma.synth.lang import NamePool
from ainma.synth.world import SECTOR_KEYS, SECTORS

KB_FMT3: list[Fmt] = ["txt", "docx", "pdf"]
KB_FMT4: list[Fmt] = ["txt", "docx", "pdf", "txt"]
PROCESS = "Standard sell-side process"
NDA = "Bank NDA template"
SPA = "the bank SPA template"


def _ctx(label: str) -> dict[str, str]:
    sec = SECTORS[SECTOR_KEYS[0]]
    return filler.context(
        "The bank", label, sec.products, sec.customers, sec.site, "Central Europe", "Central Europe"
    )


def build_kb(params: Params, book: FactBook, names: NamePool) -> list[DocSpec]:
    rng = rng_for(params.seed, "kb")
    weeks = float(rng.randrange(16, 25))
    nda_months = float(rng.choice([24, 36]))
    fee = round(rng.uniform(1.5, 3.5), 1)
    docs: list[DocSpec] = []

    def new(doc_id: str, fmt: Fmt, title: str, when: date) -> tuple[DocSpec, DocWriter]:
        spec = DocSpec(
            id=doc_id,
            folder="kb",
            fmt=fmt,
            title=title,
            doc_type=DocType.INTERNAL_REFERENCE,
            published_on=when,
            deal_id=None,
        )
        docs.append(spec)
        return spec, DocWriter(spec, book, rng_for(params.seed, "doc", doc_id), params)

    def body(spec: DocSpec, theme: str, paragraphs: int = 3) -> None:
        for _ in range(paragraphs):
            spec.para(filler.paragraph(rng, theme, _ctx("mid-sized companies"), 4))

    spec, w = new("doc_kb_buyside_playbook", "txt", "Sell-side process playbook", date(2024, 9, 1))
    spec.heading("Sell-side process playbook")
    spec.para(f"{MARK} Internal reference for deal teams.")
    spec.para(
        w.stated(PROCESS, "process_weeks", "static", weeks, with_entity=True, form="lit", force=0)
    )
    spec.para(
        w.stated(PROCESS, "bidder_rounds", "static", 2.0, with_entity=True, form="lit", force=0)
    )
    body(spec, "process")

    spec, w = new("doc_kb_nda_handling", "docx", "NDA handling guide", date(2024, 6, 12))
    spec.heading("NDA handling guide")
    spec.para(f"{MARK} Internal reference for deal teams.")
    spec.para(
        w.stated(
            NDA, "nda_term_months", "static", nda_months, with_entity=True, form="lit", force=0
        )
    )
    body(spec, "governance")

    spec, w = new(
        "doc_kb_bidder_communication", "txt", "Bidder communication protocol", date(2025, 2, 3)
    )
    spec.heading("Bidder communication protocol")
    spec.para(f"{MARK} Internal reference for deal teams.")
    spec.para(
        w.stated(PROCESS, "bidder_rounds", "static", 3.0, with_entity=True, form="lit", force=0)
    )
    body(spec, "process")

    spec, w = new(
        "doc_kb_process_timetable", "pdf", "Process timetable template", date(2024, 11, 20)
    )
    spec.heading("Process timetable template")
    spec.para(f"{MARK} Template.")
    spec.para(
        w.stated(PROCESS, "process_weeks", "static", weeks, with_entity=True, form="lit", force=0)
    )
    body(spec, "process")

    spec, w = new("doc_kb_clean_team", "txt", "Clean team guide", date(2024, 4, 8))
    spec.heading("Clean team guide")
    spec.para(f"{MARK} Internal reference for deal teams.")
    body(spec, "governance")

    spec, w = new("doc_kb_dataroom_index", "docx", "Data room index template", date(2024, 5, 2))
    spec.heading("Data room index template")
    spec.para(f"{MARK} Template.")
    body(spec, "process")

    spec, w = new(
        "doc_kb_spa_template", "pdf", "Share purchase agreement template", date(2024, 8, 15)
    )
    spec.heading("Share purchase agreement template")
    spec.para(f"{MARK} Template.")
    spec.para(w.stated(SPA, "break_fee_pct", "static", fee, with_entity=True, form="lit", force=0))
    body(spec, "governance")

    spec, w = new("doc_kb_nda_template", "docx", "NDA template", date(2024, 7, 9))
    spec.heading("NDA template")
    spec.para(f"{MARK} Template.")
    spec.para(
        w.stated(
            NDA, "nda_term_months", "static", nda_months, with_entity=True, form="lit", force=0
        )
    )
    body(spec, "governance", 2)

    spec, w = new("doc_kb_loi_template", "txt", "Letter of intent template", date(2024, 3, 14))
    spec.heading("Letter of intent template")
    spec.para(f"{MARK} Template.")
    body(spec, "process")

    spec, w = new("doc_kb_teaser_template", "txt", "Teaser template", date(2024, 2, 21))
    spec.heading("Teaser template")
    spec.para(f"{MARK} Template.")
    body(spec, "overview")

    for k in range(12):
        when = date(2024, 1 + k % 12, 5 + k)
        spec, w = new(
            f"doc_kb_precedent_{k + 1:02d}",
            KB_FMT3[k % 3],
            f"Precedent memo {k + 1:02d}",
            when,
        )
        spec.heading(f"Precedent memo {k + 1:02d}")
        spec.para(f"{MARK} Precedent transactions reviewed by the deal team.")
        for _ in range(2):
            target = f"Precedent transaction {names.stem()}"
            multiple = round(rng.uniform(6.5, 13.5), 1)
            spec.para(
                w.stated(
                    target,
                    "precedent_multiple",
                    "static",
                    multiple,
                    with_entity=True,
                    form="lit",
                    force=1,
                )
            )
        body(spec, "markets", 2)

    for k, key in enumerate(SECTOR_KEYS):
        sec = SECTORS[key]
        spec, w = new(
            f"doc_kb_sector_{key}",
            KB_FMT4[k % 4],
            f"Sector guide: {sec.label}",
            date(2024, 10, 1 + k),
        )
        spec.heading(f"Sector guide: {sec.label}")
        spec.para(f"{MARK} Sector reference for deal teams.")
        median = round(rng.uniform(7.0, 12.0), 1)
        spec.para(
            w.stated(
                f"the median {sec.label} precedent",
                "precedent_multiple",
                "static",
                median,
                with_entity=True,
                form="lit",
                force=1,
            )
        )
        spec.para(
            filler.paragraph(
                rng,
                "markets",
                filler.context(
                    "The sector",
                    sec.label,
                    sec.products,
                    sec.customers,
                    sec.site,
                    "Central Europe",
                    "Central Europe",
                ),
                4,
            )
        )
    return docs
