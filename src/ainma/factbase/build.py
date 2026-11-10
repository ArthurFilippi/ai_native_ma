"""Build `structured/factbase.json` from the planted facts of a seed (pure, deterministic)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from ainma.contracts import TIER_BY_DOCTYPE, BuyerProfile, Deal, DocStatus
from ainma.factbase.model import Company, FactBaseFile, Provenance, SourcedValue, StructuredFact
from ainma.ingest.chunker import chunk_id as _chunk_id_of
from ainma.truth import Fact, ManifestEntry


def _chunk_of(fact: Fact) -> str:
    """The stored chunk holding the primary span: a support chunk of the fact's own page."""
    prefix = _chunk_id_of(fact.document_id, fact.page, 1)[: -len("01")]
    for chunk in fact.support_chunk_ids:
        if chunk.startswith(prefix):
            return chunk
    raise ValueError(f"{fact.id}: no support chunk on page {fact.page} of {fact.document_id}")


def _provenance(fact: Fact, entry: ManifestEntry) -> Provenance:
    return Provenance(
        document_id=entry.id,
        doc_title=entry.title,
        doc_type=entry.doc_type,
        tier=TIER_BY_DOCTYPE[entry.doc_type],
        published_on=entry.published_on,
        status=entry.status,
        chunk_id=_chunk_of(fact),
        page=fact.page,
        char_start=fact.char_start,
        char_end=fact.char_end,
        quote=fact.quote,
    )


def build_factbase(
    facts: Sequence[Fact],
    manifest: Sequence[ManifestEntry],
    deals: Sequence[Deal],
    buyers: Sequence[BuyerProfile],
) -> FactBaseFile:
    entries = {e.id: e for e in manifest}
    buyer_by_name = {b.name: b.id for b in buyers}
    groups: dict[tuple[str | None, str, str, str], list[Fact]] = defaultdict(list)
    for fact in facts:
        entry = entries[fact.document_id]
        if entry.status is not DocStatus.CURRENT:
            continue  # superseded and withdrawn documents are never a source of record
        groups[(fact.deal_id, fact.entity, fact.metric, fact.period)].append(fact)

    def rank(fact: Fact) -> tuple[int, int, str]:
        entry = entries[fact.document_id]
        published = entry.published_on.toordinal() if entry.published_on else 0
        return (int(TIER_BY_DOCTYPE[entry.doc_type]), -published, entry.id)

    records: list[StructuredFact] = []
    for key in sorted(groups, key=lambda k: (k[0] or "", k[1], k[2], k[3])):
        deal_id, entity, metric, period = key
        ordered = sorted(groups[key], key=rank)
        best = ordered[0]
        seen_docs = {best.document_id}
        others: list[SourcedValue] = []
        for fact in ordered[1:]:
            if fact.document_id in seen_docs:
                continue
            seen_docs.add(fact.document_id)
            others.append(
                SourcedValue(
                    value=fact.value, provenance=_provenance(fact, entries[fact.document_id])
                )
            )
        records.append(
            StructuredFact(
                id=f"sf_{len(records) + 1:05d}",
                deal_id=deal_id,
                entity=entity,
                entity_id=buyer_by_name.get(entity),
                metric=metric,
                period=period,
                value=best.value,
                unit=best.unit,
                provenance=_provenance(best, entries[best.document_id]),
                others=others,
            )
        )
    companies = _companies(facts, deals)
    return FactBaseFile(companies=companies, facts=records)


def _companies(facts: Sequence[Fact], deals: Sequence[Deal]) -> list[Company]:
    """The target of each deal: the entity of the deal's own revenue facts stated by its
    documents of best tier (a similarly named company in a trade article is not the target)."""
    out: list[Company] = []
    for deal in sorted(deals, key=lambda d: d.id):
        counts: dict[str, int] = defaultdict(int)
        for fact in facts:
            if fact.deal_id == deal.id and fact.metric == "revenue":
                counts[fact.entity] += 1
        if not counts:
            continue
        name = max(sorted(counts), key=lambda n: counts[n])
        out.append(
            Company(
                deal_id=deal.id, name=name, sector=deal.sector, geographies=list(deal.geographies)
            )
        )
    return out
