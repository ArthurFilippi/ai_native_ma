"""A hand-written universe of six buyers around the mini data room, with the documents that
support (or do not support) each criterion. All names and numbers are fictional.

| buyer       | type      | what the documents establish                                          |
|-------------|-----------|-----------------------------------------------------------------------|
| b_nordvik   | financial | fund size, investment period to 2028, one acquisition, no share data  |
| b_tiny      | financial | fund size EUR 200m: the cheque is far above 40% (dealbreaker)         |
| b_lonely    | financial | no document at all: every textual criterion is unknown                |
| b_orbis     | strategic | market cap, 12% share, one acquisition, widely held                   |
| b_granite   | strategic | transformational size, three acquisitions, 30% share, state stake     |
| b_software  | financial | software sector: fails the sector prefilter                           |
"""

from __future__ import annotations

import hashlib
from datetime import date

from ainma.contracts import BuyerProfile, BuyerType, DocType, DocumentMeta
from ainma.store import SqliteStore
from tests.fixtures.tiny import MARK, TinyDoc, chunk_document
from tests.fixtures_biz.data_room import DEAL_ID, load_data_room

SECTOR = "industrial components"


def _profile(
    buyer_id: str,
    name: str,
    buyer_type: BuyerType,
    size: float,
    *,
    sectors: list[str] | None = None,
    vintage: int | None = None,
) -> BuyerProfile:
    return BuyerProfile(
        id=buyer_id,
        name=name,
        buyer_type=buyer_type,
        sectors=sectors or [SECTOR],
        geographies=["DACH"],
        size_eur_m=size,
        fund_vintage_year=vintage,
    )


BUYERS = [
    _profile(
        "b_nordvik", "Nordvik Industrial Partners III", BuyerType.FINANCIAL, 1800, vintage=2022
    ),
    _profile("b_tiny", "Tiny Capital Fund I", BuyerType.FINANCIAL, 200, vintage=2021),
    _profile("b_lonely", "Lonely Equity Fund II", BuyerType.FINANCIAL, 1000, vintage=2023),
    _profile("b_orbis", "Orbis Group", BuyerType.STRATEGIC, 3000),
    _profile("b_granite", "Granite Holdings", BuyerType.STRATEGIC, 500),
    _profile(
        "b_software",
        "Bitwise Capital",
        BuyerType.FINANCIAL,
        900,
        sectors=["enterprise software"],
        vintage=2022,
    ),
]


def _doc(
    doc_id: str,
    title: str,
    doc_type: DocType,
    text: str,
    published_on: date,
    *,
    entity_id: str | None = None,
    deal_id: str | None = None,
) -> TinyDoc:
    pages = [f"{MARK}\n\n{text}"]
    meta = DocumentMeta(
        id=doc_id,
        deal_id=deal_id,
        entity_id=entity_id,
        title=title,
        doc_type=doc_type,
        published_on=published_on,
        n_pages=1,
        sha256=hashlib.sha256(pages[0].encode()).hexdigest(),
    )
    return TinyDoc(meta, pages)


def _press(doc_id: str, entity: str, text: str, when: date) -> TinyDoc:
    return _doc(
        doc_id, f"Press release {doc_id}", DocType.PRESS_RELEASE, text, when, entity_id=entity
    )


def buyer_documents() -> list[TinyDoc]:
    return [
        _doc(
            "doc_nv_filing",
            "Nordvik fund III, regulatory filing",
            DocType.REGULATORY_FILING,
            "Fund III has total commitments of EUR 1.8 billion.\n\n"
            "The investment period of Fund III ends in June 2028.\n\n"
            "Nordvik Industrial Partners III invests in industrial components businesses in DACH.",
            date(2025, 4, 30),
            entity_id="b_nordvik",
        ),
        _press(
            "doc_nv_pr",
            "b_nordvik",
            "Nordvik Industrial Partners III completed the acquisition of Brandt Fertigung, an "
            "industrial components maker, in March 2025.",
            date(2025, 3, 20),
        ),
        _doc(
            "doc_tiny_filing",
            "Tiny Capital fund I, regulatory filing",
            DocType.REGULATORY_FILING,
            "Tiny Capital Fund I has total commitments of EUR 200 million.",
            date(2025, 1, 15),
            entity_id="b_tiny",
        ),
        _doc(
            "doc_orbis_ar",
            "Orbis Group, annual report excerpt",
            DocType.COMPANY_REPORT,
            "Orbis Group has a market capitalisation of EUR 3.0 billion.\n\n"
            "Orbis Group holds a market share of 12 percent in industrial components.\n\n"
            "Orbis Group is widely held and has no state ownership.",
            date(2025, 5, 20),
            entity_id="b_orbis",
        ),
        _press(
            "doc_orbis_pr",
            "b_orbis",
            "Orbis Group acquired a sensor manufacturer in industrial components in February 2025.",
            date(2025, 2, 10),
        ),
        _doc(
            "doc_granite_ar",
            "Granite Holdings, annual report excerpt",
            DocType.COMPANY_REPORT,
            "Granite Holdings has a market capitalisation of EUR 500 million.\n\n"
            "Granite Holdings holds a market share of 30 percent in industrial components.\n\n"
            "A sovereign wealth fund holds 20 percent of Granite Holdings.",
            date(2025, 5, 2),
            entity_id="b_granite",
        ),
        _press(
            "doc_granite_pr1",
            "b_granite",
            "Granite Holdings acquired a bearing producer in industrial components in "
            "January 2025.",
            date(2025, 1, 12),
        ),
        _press(
            "doc_granite_pr2",
            "b_granite",
            "Granite Holdings acquired a valve maker in industrial components in March 2025.",
            date(2025, 3, 3),
        ),
        _press(
            "doc_granite_pr3",
            "b_granite",
            "Granite Holdings acquired a gear specialist in industrial components in April 2025.",
            date(2025, 4, 8),
        ),
        _doc(
            "doc_mgmt_pres",
            "Project Aurora, management presentation",
            DocType.DEAL_DOCUMENT,
            "Aurora holds a market share of 15 percent in industrial components in Central Europe.",
            date(2025, 3, 20),
            deal_id=DEAL_ID,
        ),
    ]


async def load_universe(store: SqliteStore) -> list[BuyerProfile]:
    """Load the data room and the buyer documents, return the buyer profiles."""
    await load_data_room(store)
    for doc in buyer_documents():
        await store.put_document(doc.meta, doc.pages)
        await store.put_chunks(chunk_document(doc))
    return list(BUYERS)
