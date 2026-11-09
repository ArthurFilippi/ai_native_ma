"""A hand-written mini data room for the KPI tests: statements as pipe tables plus a few sentences.

All values are synthetic. `TRUTH` holds the numbers the tables were written from (EUR m), so
tests compare extraction with a known answer. Everything is loaded through the public store API.
"""

from __future__ import annotations

import hashlib
from datetime import date

from ainma.contracts import (
    Deal,
    DocStatus,
    DocType,
    DocumentMeta,
    Membership,
    Role,
    User,
)
from ainma.store import SqliteStore
from tests.fixtures.tiny import MARK, TinyDoc, chunk_document

PERIODS = ["FY2020", "FY2021", "FY2022", "FY2023", "FY2024"]
DEAL_ID = "deal_aurora"

ROWS: dict[str, list[float]] = {
    "revenue": [150.2, 158.9, 165.0, 168.0, 182.4],
    "cogs": [96.1, 100.4, 103.5, 105.6, 112.2],
    "ebitda": [24.1, 26.0, 27.4, 28.9, 31.5],
    "ebit": [17.0, 18.3, 19.8, 21.1, 23.6],
    "interest_expense": [3.1, 3.0, 2.8, 2.6, 2.4],
    "net_income": [9.8, 10.9, 12.1, 13.0, 14.9],
    "operating_cash_flow": [20.0, 21.5, 22.4, 24.0, 26.1],
    "capex": [8.0, 8.4, 9.0, 9.2, 10.1],
    "current_assets": [70.0, 73.2, 75.0, 78.4, 83.0],
    "current_liabilities": [41.0, 42.3, 43.0, 44.1, 46.0],
    "cash": [12.0, 13.5, 14.0, 16.2, 19.4],
    "total_debt": [60.0, 58.0, 55.0, 52.0, 48.0],
    "total_assets": [190.0, 198.5, 205.0, 212.3, 224.0],
    "total_equity": [80.0, 86.4, 93.0, 100.5, 110.2],
    "total_headcount": [1150, 1170, 1190, 1210, 1250],
}

LABELS = {
    "revenue": "Revenue",
    "cogs": "Cost of goods sold",
    "ebitda": "EBITDA",
    "ebit": "EBIT",
    "interest_expense": "Interest expense",
    "net_income": "Net income",
    "operating_cash_flow": "Operating cash flow",
    "capex": "Capital expenditures",
    "current_assets": "Total current assets",
    "current_liabilities": "Total current liabilities",
    "cash": "Cash and cash equivalents",
    "total_debt": "Total debt",
    "total_assets": "Total assets",
    "total_equity": "Total equity",
    "total_headcount": "Total headcount",
}

STATEMENTS = {
    "Consolidated income statement (EUR m)": [
        "revenue",
        "cogs",
        "ebitda",
        "ebit",
        "interest_expense",
        "net_income",
    ],
    "Consolidated balance sheet (EUR m)": [
        "current_assets",
        "current_liabilities",
        "cash",
        "total_debt",
        "total_assets",
        "total_equity",
    ],
    "Consolidated cash flow statement (EUR m)": ["operating_cash_flow", "capex"],
    "Workforce": ["total_headcount"],
}


def _fmt(value: float) -> str:
    return f"{int(value):,}" if float(value).is_integer() and value >= 1000 else f"{value:.1f}"


def statement_text(title: str, keys: list[str]) -> str:
    header = "Line item | " + " | ".join(PERIODS)
    rows = [f"{LABELS[k]} | " + " | ".join(_fmt(v) for v in ROWS[k]) for k in keys]
    return "\n".join([title, header, *rows])


def make_doc(
    doc_id: str,
    title: str,
    doc_type: DocType,
    pages: list[str],
    published_on: date,
    *,
    deal_id: str | None = DEAL_ID,
    entity_id: str | None = None,
    status: DocStatus = DocStatus.CURRENT,
) -> TinyDoc:
    meta = DocumentMeta(
        id=doc_id,
        deal_id=deal_id,
        entity_id=entity_id,
        title=title,
        doc_type=doc_type,
        published_on=published_on,
        status=status,
        n_pages=len(pages),
        sha256=hashlib.sha256("\n".join(pages).encode()).hexdigest(),
    )
    return TinyDoc(meta, pages)


def documents() -> list[TinyDoc]:
    pages = [f"{MARK}\n\n" + "\n\n".join(statement_text(t, k) for t, k in STATEMENTS.items())]
    model = make_doc(
        "doc_model",
        "Project Aurora, financial model",
        DocType.DEAL_DOCUMENT,
        pages,
        date(2025, 3, 14),
    )
    cim = make_doc(
        "doc_cim",
        "Project Aurora, Confidential Information Memorandum",
        DocType.DEAL_DOCUMENT,
        [
            f"{MARK}\n\nNet revenue for FY2024 reached EUR 182.4 million (FY2023: EUR 168.0 "
            "million).\n\nGross margin was 38.5 percent in FY2024, against 37.1 percent in "
            "FY2023.\n\nThe largest customer represented 17 percent of FY2024 revenue.\n\n"
            "Revenue growth was 8.6 percent in FY2024.\n\nAurora employed 1,250 people at the "
            "end of FY2024."
        ],
        date(2025, 3, 14),
    )
    news = make_doc(
        "doc_news_17",
        "Trade press: Aurora Components posts record year",
        DocType.PRESS_ARTICLE,
        [f"{MARK}\n\nAurora booked roughly EUR 179 million of revenue in 2024."],
        date(2025, 2, 2),
    )
    return [model, cim, news]


async def load_data_room(store: SqliteStore) -> None:
    await store.put_user(User(id="u_lead", name="Lena Lead"))
    await store.put_user(User(id="u_outsider", name="Omar Outsider"))
    await store.put_deal(Deal(id=DEAL_ID, name="Project Aurora", sector="industrial components"))
    await store.put_membership(Membership(deal_id=DEAL_ID, user_id="u_lead", role=Role.LEAD))
    for doc in documents():
        await store.put_document(doc.meta, doc.pages)
        chunks = [
            c.model_copy(update={"kind": "table" if " | " in c.text else "text"})
            for c in chunk_document(doc)
        ]
        await store.put_chunks(chunks)
