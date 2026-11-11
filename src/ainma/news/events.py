"""Market events of a deal space, consolidated from its news documents (D94).

Each news passage goes to the `extract_events` task; code checks that every quote is a verbatim
span of the passage and builds the citation (a draft without a verbatim quote is dropped). Reports
are then grouped by (kind, actor, counterparty): duplicates from other outlets add citations to
one event, a denial turns a rumour into `denied`, a correction replaces a price and keeps the first
figure as a superseded citation. A denied rumour is never reported as a fact.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from ainma.contracts import (
    AccessContext,
    Chunk,
    Citation,
    DocType,
    DocumentMeta,
    MarketEvent,
)
from ainma.llm.base import LLM
from ainma.llm.tasks import TASK_EXTRACT_EVENTS
from ainma.news.schemas import (
    EXTRACT_EVENTS_PROMPT,
    EventDraft,
    ExtractEventsRequest,
    ExtractEventsResult,
)
from ainma.pipeline.write import build_citation
from ainma.store.base import Store

logger = logging.getLogger(__name__)

NEWS_TYPES = (DocType.PRESS_ARTICLE, DocType.PRESS_RELEASE)


@dataclass(frozen=True)
class Report:
    draft: EventDraft
    citation: Citation
    document: DocumentMeta


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


async def extract_reports(
    chunks: list[Chunk], documents: dict[str, DocumentMeta], llm: LLM
) -> list[Report]:
    reports: list[Report] = []
    for chunk in chunks:
        result, _ = await llm.complete_json(
            task=TASK_EXTRACT_EVENTS,
            system=EXTRACT_EVENTS_PROMPT,
            user=ExtractEventsRequest(text=chunk.text).model_dump_json(),
            schema=ExtractEventsResult,
            stage="events",
        )
        document = documents[chunk.document_id]
        for draft in result.events:
            citation = build_citation(chunk, document, draft.quote) if draft.quote.strip() else None
            if citation is None:
                logger.info("event draft dropped, quote not verbatim: %s", draft.quote[:80])
                continue
            reports.append(Report(draft=draft, citation=citation, document=document))
    return reports


def consolidate(reports: list[Report], buyer_ids: dict[str, str]) -> list[MarketEvent]:
    groups: dict[tuple[str, str, str], list[Report]] = defaultdict(list)
    seen: set[tuple[str, str, str, str, str]] = set()
    for report in reports:
        d = report.draft
        key: tuple[str, str, str] = (str(d.kind), _norm(d.actor), _norm(d.counterparty))
        once = (*key, report.document.id, d.stance)
        if once in seen:
            continue  # a document repeats its headline in the body: one report per document
        seen.add(once)
        groups[key].append(report)
    events: list[MarketEvent] = []
    for group in sorted(groups):
        items = sorted(
            groups[group],
            key=lambda r: (
                r.document.published_on or r.citation.published_on or 0,
                r.citation.chunk_id,
            ),
        )
        kind = items[0].draft.kind
        reports_ = [r for r in items if r.draft.stance == "report"]
        denials = [r for r in items if r.draft.stance == "denial"]
        corrections = [r for r in items if r.draft.stance == "correction"]
        first = (reports_ or items)[0]
        value = first.draft.value_eur_m
        superseded: list[Citation] = []
        status: Literal["confirmed", "unconfirmed", "denied", "corrected"]
        if kind == "rumour":
            status = "denied" if denials else "unconfirmed"
        elif corrections:
            status = "corrected"
            value = corrections[-1].draft.value_eur_m
            superseded = [r.citation for r in reports_]
        else:
            status = "confirmed"
        cited = [r.citation for r in items if r.citation not in superseded]
        material = "|".join(group)
        events.append(
            MarketEvent(
                id="ev_" + hashlib.sha256(material.encode()).hexdigest()[:10],
                kind=kind,
                actor=first.draft.actor,
                buyer_id=buyer_ids.get(_norm(first.draft.actor)),
                counterparty=first.draft.counterparty,
                event_date=first.document.published_on,
                status=status,
                value_eur_m=value,
                citations=cited,
                superseded_citations=superseded,
                n_reports=len(items),
            )
        )
    return sorted(events, key=lambda e: (e.event_date is None, e.event_date, e.id))


async def market_events(
    deal_id: str, *, store: Store, access: AccessContext, llm: LLM
) -> list[MarketEvent]:
    """Events reported by the news documents of the deal space, consolidated and cited.

    Raises `LookupError` when the deal is not visible to `access`."""
    if await store.get_deal(deal_id, access) is None:
        raise LookupError(f"deal {deal_id} not found")
    documents = {
        d.id: d
        for d in await store.list_documents(access, deal_id)
        if d.deal_id == deal_id and d.doc_type in NEWS_TYPES
    }
    chunks = [
        c
        for c in await store.candidates(access, deal_id=deal_id, doc_types=list(NEWS_TYPES))
        if c.document_id in documents
    ]
    chunks.sort(key=lambda c: c.id)
    reports = await extract_reports(chunks, documents, llm)
    buyer_ids = {_norm(b.name): b.id for b in await store.list_buyers()}
    return consolidate(reports, buyer_ids)
