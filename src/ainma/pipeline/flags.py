"""Flags computed by code from the citations and the document metadata (spec section 7)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from ainma.contracts import Citation, Claim, ClaimStatus, DocStatus, DocumentMeta, Flag, SourceTier
from ainma.retrieval.config import RankerConfig
from ainma.retrieval.ranker import independent

LOW_TIER = SourceTier.T4


def is_stale(citations: list[Citation], ranker: RankerConfig, as_of: date | None) -> bool:
    """Every supporting source is older than the freshness window of its type."""
    if as_of is None or not citations:
        return False
    return all(
        c.published_on is not None and (as_of - c.published_on).days > ranker.stale_days[c.doc_type]
        for c in citations
    )


def independent_documents(
    citations: list[Citation], documents: Mapping[str, DocumentMeta]
) -> list[DocumentMeta]:
    chosen: list[DocumentMeta] = []
    for citation in citations:
        meta = documents[citation.document_id]
        if all(independent(meta, other) for other in chosen) and meta.id not in {
            o.id for o in chosen
        }:
            chosen.append(meta)
    return chosen


def apply_flags(
    claims: list[Claim],
    *,
    documents: Mapping[str, DocumentMeta],
    ranker: RankerConfig,
    as_of: date | None,
) -> list[Claim]:
    out: list[Claim] = []
    for claim in claims:
        if claim.status is not ClaimStatus.SOURCED:
            out.append(claim)
            continue
        flags = list(claim.flags)
        if is_stale(claim.citations, ranker, as_of):
            flags.append(Flag.STALE)
        if all(documents[c.document_id].status is DocStatus.SUPERSEDED for c in claim.citations):
            flags.append(Flag.SUPERSEDED)
        sources = independent_documents(claim.citations, documents)
        if len(sources) == 1 and sources[0].tier >= LOW_TIER:
            flags.append(Flag.SINGLE_LOW_TIER_SOURCE)
        out.append(claim.model_copy(update={"flags": flags}))
    return out
