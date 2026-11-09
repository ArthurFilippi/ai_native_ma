"""Tiny synthetic corpus and ground truth for the smoke run and for the unit tests.

A copy of the hand written fixture corpus (two deals, three users, general layer) with one more
document, and just enough truth to exercise every table of the report. Everything is synthetic.
These numbers prove that the flow runs, they measure nothing.
"""

from __future__ import annotations

import hashlib
from datetime import date

from ainma.contracts import (
    BuyerProfile,
    BuyerType,
    Chunk,
    CriterionStatus,
    Deal,
    DocStatus,
    DocType,
    DocumentMeta,
    Membership,
    Role,
    User,
)
from ainma.evaluation.groundtruth import TruthBundle
from ainma.store import SqliteStore, Store
from ainma.truth import (
    BuyerTruth,
    ContradictionTruth,
    Fact,
    JudgeLabel,
    KpiTruth,
    Query,
    StaleCase,
    Unanswerable,
    UsersFile,
)

MARK = "SYNTHETIC DOCUMENT, fictional data."
CIM_P2 = (
    "Net revenue for FY2024 reached EUR 182.4 million (FY2023: EUR 168.0 million).\n\n"
    "Gross margin was 38.5 percent in FY2024.\n\n"
    "The largest customer represented 17 percent of FY2024 revenue."
)


def _doc(
    doc_id: str,
    title: str,
    doc_type: DocType,
    pages: list[str],
    *,
    deal_id: str | None,
    published_on: date,
    status: DocStatus = DocStatus.CURRENT,
) -> tuple[DocumentMeta, list[str]]:
    meta = DocumentMeta(
        id=doc_id,
        deal_id=deal_id,
        title=title,
        doc_type=doc_type,
        published_on=published_on,
        status=status,
        n_pages=len(pages),
        sha256=hashlib.sha256("\n".join(pages).encode()).hexdigest(),
    )
    return meta, pages


def smoke_documents() -> list[tuple[DocumentMeta, list[str]]]:
    return [
        _doc(
            "doc_cim",
            "Project Aurora, Confidential Information Memorandum",
            DocType.DEAL_DOCUMENT,
            [f"{MARK}\n\nProject Aurora is a producer of industrial components.", CIM_P2],
            deal_id="deal_aurora",
            published_on=date(2025, 3, 14),
        ),
        _doc(
            "doc_news_17",
            "Trade press: Aurora Components posts record year",
            DocType.PRESS_ARTICLE,
            [
                f"{MARK}\n\nAurora booked roughly EUR 179 million of revenue in 2024.\n\n"
                "The company is advised by a sell-side team."
            ],
            deal_id="deal_aurora",
            published_on=date(2025, 2, 2),
        ),
        _doc(
            "doc_ar",
            "Aurora annual report excerpt",
            DocType.COMPANY_REPORT,
            [f"{MARK}\n\nGross margin was 38.5 percent in FY2024 according to the annual report."],
            deal_id="deal_aurora",
            published_on=date(2025, 4, 2),
        ),
        _doc(
            "doc_pr_orig",
            "Aurora press release (original, withdrawn)",
            DocType.PRESS_RELEASE,
            [f"{MARK}\n\nAurora reports FY2024 revenue of EUR 190.0 million."],
            deal_id="deal_aurora",
            published_on=date(2025, 2, 10),
            status=DocStatus.WITHDRAWN,
        ),
        _doc(
            "doc_other_cim",
            "Project Borealis, Confidential Information Memorandum",
            DocType.DEAL_DOCUMENT,
            [f"{MARK}\n\nBorealis net revenue for FY2024 reached EUR 55.5 million."],
            deal_id="deal_borealis",
            published_on=date(2025, 4, 1),
        ),
        _doc(
            "doc_playbook",
            "Sell-side process playbook",
            DocType.INTERNAL_REFERENCE,
            [
                f"{MARK}\n\nA sell-side process starts with preparation of the teaser and the "
                "information memorandum.\n\nBidder communication follows a single channel."
            ],
            deal_id=None,
            published_on=date(2024, 9, 1),
        ),
    ]


def _chunks(meta: DocumentMeta, pages: list[str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page_no, text in enumerate(pages, start=1):
        cursor = 0
        for index, paragraph in enumerate(text.split("\n\n")):
            start = text.index(paragraph, cursor)
            cursor = start + len(paragraph)
            chunks.append(
                Chunk(
                    id=f"{meta.id}_p{page_no}_{index:02d}",
                    document_id=meta.id,
                    deal_id=meta.deal_id,
                    page=page_no,
                    char_start=start,
                    char_end=cursor,
                    text=paragraph,
                    doc_type=meta.doc_type,
                    published_on=meta.published_on,
                )
            )
    return chunks


async def load_smoke_store() -> Store:
    store = await SqliteStore.open(":memory:")
    for user in (User(id="u_lead", name="Lena Lead"), User(id="u_analyst", name="Alex Analyst")):
        await store.put_user(user)
    await store.put_deal(Deal(id="deal_aurora", name="Project Aurora", sector="industrial"))
    await store.put_deal(Deal(id="deal_borealis", name="Project Borealis", sector="software"))
    await store.put_membership(Membership(deal_id="deal_aurora", user_id="u_lead", role=Role.LEAD))
    await store.put_membership(
        Membership(deal_id="deal_aurora", user_id="u_analyst", role=Role.MEMBER)
    )
    for meta, pages in smoke_documents():
        await store.put_document(meta, pages)
        await store.put_chunks(_chunks(meta, pages))
    return store


def _fact(row: tuple[str, str, str, float, str, str, list[str], list[str]], deal_id: str) -> Fact:
    fact_id, metric, period, value, unit, document_id, support, keywords = row
    return Fact(
        id=fact_id,
        deal_id=deal_id,
        entity=deal_id,
        metric=metric,
        period=period,
        value=value,
        unit=unit,
        document_id=document_id,
        page=1,
        char_start=0,
        char_end=1,
        quote="synthetic",
        support_chunk_ids=support,
        keywords=keywords,
    )


CIM0, CIM1, CIM2 = "doc_cim_p2_00", "doc_cim_p2_01", "doc_cim_p2_02"
AR1, NEWS1, PR1, BOR1 = (
    "doc_ar_p1_01",
    "doc_news_17_p1_01",
    "doc_pr_orig_p1_01",
    "doc_other_cim_p1_01",
)

FACT_ROWS = [
    ("f_rev24", "revenue", "FY2024", 182.4, "EUR m", "doc_cim", [CIM0], ["revenue", "FY2024"]),
    ("f_rev23", "revenue", "FY2023", 168.0, "EUR m", "doc_cim", [CIM0], ["revenue", "FY2023"]),
    (
        "f_gm24",
        "gross_margin",
        "FY2024",
        38.5,
        "%",
        "doc_cim",
        [CIM1, AR1],
        ["gross margin", "FY2024"],
    ),
    ("f_gm24_ar", "gross_margin", "FY2024", 38.5, "%", "doc_ar", [AR1], ["gross margin", "FY2024"]),
    (
        "f_cust",
        "top_customer_share",
        "FY2024",
        17.0,
        "%",
        "doc_cim",
        [CIM2],
        ["largest customer", "FY2024"],
    ),
    ("f_news", "revenue", "FY2024", 179.0, "EUR m", "doc_news_17", [NEWS1], ["revenue", "2024"]),
    ("f_pr", "revenue", "FY2024", 190.0, "EUR m", "doc_pr_orig", [PR1], ["revenue", "FY2024"]),
]
QUERY_ROWS = [
    ("q_smoke_1", "deal_aurora", "What was Aurora net revenue for FY2024?", "f_rev24", {CIM0: 2}),
    (
        "q_smoke_2",
        "deal_aurora",
        "What was Aurora gross margin in FY2024?",
        "f_gm24",
        {CIM1: 2, AR1: 2},
    ),
    (
        "q_smoke_3",
        "deal_aurora",
        "What share of FY2024 revenue did the largest customer represent?",
        "f_cust",
        {CIM2: 2},
    ),
    ("q_smoke_4", "deal_aurora", "What was Aurora net revenue for FY2023?", "f_rev23", {CIM0: 2}),
    (
        "q_smoke_5",
        "deal_aurora",
        "What revenue did trade press report for Aurora in 2024?",
        "f_news",
        {NEWS1: 2},
    ),
    ("q_smoke_6", "deal_borealis", "What was Borealis net revenue for FY2024?", "f_bor", {BOR1: 2}),
    (
        "q_smoke_7",
        "deal_aurora",
        "Which FY2024 revenue did the original Aurora press release report?",
        "f_pr",
        {PR1: 2, CIM0: 1},
    ),
]
UNANSWERABLE_ROWS = [
    ("u_smoke_1", "deal_aurora", "What is the CEO compensation package?", False),
    ("u_smoke_2", "deal_aurora", "Which patents does Aurora own?", False),
    ("u_smoke_3", "deal_aurora", "What is the FY2026 revenue guidance?", True),
    ("u_smoke_4", "deal_borealis", "How many employees does Borealis have?", False),
    ("u_smoke_5", "deal_aurora", "What was Aurora net revenue for FY2019?", True),
    ("u_smoke_6", "deal_aurora", "Who is the head of research?", False),
]
JUDGE_ROWS = [
    ("j_1", "Net revenue for FY2024 reached EUR 182.4 million.", CIM0, "supported", "none", "test"),
    ("j_2", "Gross margin was 38.5 percent in FY2024.", CIM1, "supported", "none", "test"),
    (
        "j_3",
        "Gross margin was 41.5 percent in FY2024.",
        CIM1,
        "unsupported",
        "altered_number",
        "test",
    ),
    (
        "j_4",
        "Net revenue for FY2023 reached EUR 182.4 million.",
        CIM0,
        "unsupported",
        "altered_period",
        "test",
    ),
    (
        "j_5",
        "Borealis net revenue for FY2024 reached EUR 182.4 million.",
        CIM0,
        "unsupported",
        "altered_entity",
        "test",
    ),
    (
        "j_6",
        "Net revenue for FY2024 reached EUR 182.4 million and gross margin was 50 percent.",
        CIM0,
        "partial",
        "half_true",
        "test",
    ),
    (
        "j_7",
        "The largest customer represented 17 percent of FY2024 revenue.",
        "doc_playbook_p1_01",
        "unsupported",
        "unrelated",
        "test",
    ),
    (
        "j_8",
        "The largest customer represented 17 percent of FY2024 revenue.",
        CIM2,
        "supported",
        "none",
        "dev",
    ),
    (
        "j_9",
        "The largest customer represented 21 percent of FY2024 revenue.",
        CIM2,
        "unsupported",
        "altered_number",
        "dev",
    ),
    (
        "j_10",
        "Net revenue for FY2024 reached EUR 182.4 million and the largest customer 30 percent.",
        CIM0,
        "partial",
        "half_true",
        "dev",
    ),
]
KPI_ROWS = [
    ("revenue", "FY2024", 182.4, "EUR m", "extract"),
    ("revenue", "FY2023", 168.0, "EUR m", "extract"),
    ("gross_margin", "FY2024", 38.5, "%", "extract"),
    ("revenue_growth", "FY2024", 8.57, "%", "compute"),
]
BUYER_ROWS = [
    ("b_smoke_a", "sector_focus", CriterionStatus.MET),
    ("b_smoke_a", "geography", CriterionStatus.MET),
    ("b_smoke_b", "sector_focus", CriterionStatus.NOT_MET),
    ("b_smoke_b", "geography", CriterionStatus.MET),
]


def smoke_truth() -> TruthBundle:
    facts = [_fact(row, "deal_aurora") for row in FACT_ROWS]
    facts.append(
        _fact(
            (
                "f_bor",
                "revenue",
                "FY2024",
                55.5,
                "EUR m",
                "doc_other_cim",
                [BOR1],
                ["revenue", "FY2024"],
            ),
            "deal_borealis",
        )
    )
    queries = [
        Query(
            id=qid,
            deal_id=deal,
            text=text,
            kind="single_fact",
            gold_fact_ids=[fact],
            relevance=relevance,
        )
        for qid, deal, text, fact, relevance in QUERY_ROWS
    ]
    unanswerable = [
        Unanswerable(id=uid, deal_id=deal, text=text, reason="absent", hard=hard)
        for uid, deal, text, hard in UNANSWERABLE_ROWS
    ]
    labels = [
        JudgeLabel.model_validate(
            {
                "id": lid,
                "claim": claim,
                "chunk_id": chunk,
                "label": label,
                "perturbation": perturbation,
                "split": split,
            }
        )
        for lid, claim, chunk, label, perturbation, split in JUDGE_ROWS
    ]
    return TruthBundle(
        deals=[
            Deal(id="deal_aurora", name="Project Aurora", sector="industrial"),
            Deal(id="deal_borealis", name="Project Borealis", sector="software"),
        ],
        users=UsersFile(
            users=[User(id="u_lead", name="Lena Lead"), User(id="u_analyst", name="Alex Analyst")],
            memberships=[
                Membership(deal_id="deal_aurora", user_id="u_lead", role=Role.LEAD),
                Membership(deal_id="deal_aurora", user_id="u_analyst", role=Role.MEMBER),
            ],
        ),
        buyers=[
            BuyerProfile(
                id="b_smoke_a",
                name="Smoke Partners I",
                buyer_type=BuyerType.FINANCIAL,
                sectors=["industrial"],
                geographies=["DACH"],
                size_eur_m=1500.0,
                ticket_min_eur_m=50.0,
                ticket_max_eur_m=200.0,
            ),
            BuyerProfile(
                id="b_smoke_b",
                name="Smoke Strategic AG",
                buyer_type=BuyerType.STRATEGIC,
                sectors=["software"],
                geographies=["EU"],
                size_eur_m=9000.0,
                listed=True,
            ),
        ],
        facts=facts,
        queries=queries,
        unanswerable=unanswerable,
        contradictions=[
            _contradiction(
                "ct_rev24",
                "contradiction",
                "Aurora FY2024 revenue",
                ["f_rev24", "f_news"],
                ["doc_cim", "doc_news_17"],
                "doc_cim",
                "contradiction",
                "q_smoke_1",
            ),
            _contradiction(
                "ct_gm24",
                "consistent_control",
                "Aurora FY2024 gross margin",
                ["f_gm24", "f_gm24_ar"],
                ["doc_cim", "doc_ar"],
                None,
                "no_contradiction",
                "q_smoke_2",
            ),
            _contradiction(
                "ct_rev24_withdrawn",
                "withdrawn",
                "Aurora FY2024 revenue (withdrawn release)",
                ["f_rev24", "f_pr"],
                ["doc_cim", "doc_pr_orig"],
                "doc_cim",
                "flag_withdrawn",
                "q_smoke_7",
            ),
        ],
        stale=[StaleCase(id="st_1", query_id="q_smoke_5", fact_id="f_news")],
        kpi_truth=[
            KpiTruth(deal_id="deal_aurora", kpi_id=k, period=p, value=v, unit=u, kind=kind)
            for k, p, v, u, kind in KPI_ROWS
        ],
        buyer_truth=[
            BuyerTruth(deal_id="deal_aurora", buyer_id=b, criterion_key=c, status=s)
            for b, c, s in BUYER_ROWS
        ],
        judge_labels=labels,
    )


def _contradiction(
    truth_id: str,
    kind: str,
    subject: str,
    fact_ids: list[str],
    document_ids: list[str],
    stronger: str | None,
    expected: str,
    query_id: str,
) -> ContradictionTruth:
    return ContradictionTruth.model_validate(
        {
            "id": truth_id,
            "kind": kind,
            "deal_id": "deal_aurora",
            "subject": subject,
            "entity": "deal_aurora",
            "metric": "revenue" if "revenue" in subject else "gross_margin",
            "period": "FY2024",
            "fact_ids": fact_ids,
            "document_ids": document_ids,
            "stronger_document_id": stronger,
            "expected": expected,
            "query_id": query_id,
        }
    )
