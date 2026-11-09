"""Tiny hand written corpus: 2 deals, 3 users, 5 documents (one general layer).

Chunks are paragraphs of page text, with exact page offsets, so the same invariants hold as in
the generated corpus. Everything here is synthetic.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from ainma.contracts import (
    Chunk,
    Deal,
    DocStatus,
    DocType,
    DocumentMeta,
    Membership,
    Role,
    User,
)
from ainma.store.base import Store

MARK = "SYNTHETIC DOCUMENT, fictional data."


@dataclass(frozen=True)
class TinyDoc:
    meta: DocumentMeta
    pages: list[str]


def _meta(
    doc_id: str,
    title: str,
    doc_type: DocType,
    pages: list[str],
    *,
    deal_id: str | None,
    published_on: date,
    status: DocStatus = DocStatus.CURRENT,
) -> TinyDoc:
    digest = hashlib.sha256("\n".join(pages).encode()).hexdigest()
    meta = DocumentMeta(
        id=doc_id,
        deal_id=deal_id,
        title=title,
        doc_type=doc_type,
        published_on=published_on,
        status=status,
        n_pages=len(pages),
        sha256=digest,
    )
    return TinyDoc(meta, pages)


def tiny_documents() -> list[TinyDoc]:
    cim = _meta(
        "doc_cim",
        "Project Aurora, Confidential Information Memorandum",
        DocType.DEAL_DOCUMENT,
        [
            f"{MARK}\n\nProject Aurora is a producer of industrial components in Central Europe.",
            "Net revenue for FY2024 reached EUR 182.4 million (FY2023: EUR 168.0 million).\n\n"
            "Gross margin was 38.5 percent in FY2024.\n\n"
            "The largest customer represented 17 percent of FY2024 revenue.",
        ],
        deal_id="deal_aurora",
        published_on=date(2025, 3, 14),
    )
    news = _meta(
        "doc_news_17",
        "Trade press: Aurora Components posts record year",
        DocType.PRESS_ARTICLE,
        [
            f"{MARK}\n\nAurora booked roughly EUR 179 million of revenue in 2024.\n\n"
            "The company is advised by a sell-side team."
        ],
        deal_id="deal_aurora",
        published_on=date(2025, 2, 2),
    )
    other = _meta(
        "doc_other_cim",
        "Project Borealis, Confidential Information Memorandum",
        DocType.DEAL_DOCUMENT,
        [
            f"{MARK}\n\nBorealis net revenue for FY2024 reached EUR 55.5 million.\n\n"
            "The Borealis codename must never be visible outside its deal team."
        ],
        deal_id="deal_borealis",
        published_on=date(2025, 4, 1),
    )
    playbook = _meta(
        "doc_playbook",
        "Sell-side process playbook",
        DocType.INTERNAL_REFERENCE,
        [
            f"{MARK}\n\nA sell-side process starts with preparation of the teaser and the "
            "information memorandum.\n\nBidder communication follows a single channel."
        ],
        deal_id=None,
        published_on=date(2024, 9, 1),
    )
    withdrawn = _meta(
        "doc_pr_orig",
        "Aurora press release (original, withdrawn)",
        DocType.PRESS_RELEASE,
        [f"{MARK}\n\nAurora reports FY2024 revenue of EUR 190.0 million."],
        deal_id="deal_aurora",
        published_on=date(2025, 2, 10),
        status=DocStatus.WITHDRAWN,
    )
    return [cim, news, other, playbook, withdrawn]


def chunk_document(doc: TinyDoc) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page_no, text in enumerate(doc.pages, start=1):
        cursor = 0
        for index, paragraph in enumerate(text.split("\n\n")):
            start = text.index(paragraph, cursor)
            end = start + len(paragraph)
            cursor = end
            chunks.append(
                Chunk(
                    id=f"{doc.meta.id}_p{page_no}_{index:02d}",
                    document_id=doc.meta.id,
                    deal_id=doc.meta.deal_id,
                    entity_id=doc.meta.entity_id,
                    page=page_no,
                    char_start=start,
                    char_end=end,
                    text=paragraph,
                    doc_type=doc.meta.doc_type,
                    published_on=doc.meta.published_on,
                )
            )
    return chunks


def tiny_users() -> list[User]:
    return [
        User(id="u_lead", name="Lena Lead"),
        User(id="u_analyst", name="Alex Analyst"),
        User(id="u_outsider", name="Omar Outsider"),
    ]


def tiny_deals() -> list[Deal]:
    return [
        Deal(id="deal_aurora", name="Project Aurora", sector="industrial components"),
        Deal(id="deal_borealis", name="Project Borealis", sector="software"),
    ]


def tiny_memberships() -> list[Membership]:
    return [
        Membership(deal_id="deal_aurora", user_id="u_lead", role=Role.LEAD),
        Membership(deal_id="deal_borealis", user_id="u_lead", role=Role.LEAD),
        Membership(deal_id="deal_aurora", user_id="u_analyst", role=Role.MEMBER),
    ]


async def load_tiny(store: Store) -> None:
    for user in tiny_users():
        await store.put_user(user)
    for deal in tiny_deals():
        await store.put_deal(deal)
    for membership in tiny_memberships():
        await store.put_membership(membership)
    for doc in tiny_documents():
        await store.put_document(doc.meta, doc.pages)
        await store.put_chunks(chunk_document(doc))
