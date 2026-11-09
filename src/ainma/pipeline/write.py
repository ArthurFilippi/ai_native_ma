"""Write: the model drafts claims from numbered passages, code builds every citation.

The model returns passage numbers and an exact quote, never offsets. Code locates the quote in
the chunk text (exactly, or up to whitespace, in which case the real slice becomes the quote),
and fills page and character offsets. A quote that is not in the chunk rejects the evidence, a
claim without valid evidence is rejected, an inferred claim whose sources were rejected too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ainma.contracts import Chunk, Citation, Claim, ClaimStatus, DocumentMeta
from ainma.llm.base import LLM, Usage
from ainma.llm.tasks import TASK_WRITE
from ainma.pipeline import prompts
from ainma.pipeline.schemas import (
    DraftClaim,
    DroppedClaim,
    NumberedPassage,
    WriteRequest,
    WriteResult,
)
from ainma.retrieval.engine import SearchHit


def locate_quote(quote: str, chunk_text: str) -> tuple[int, str] | None:
    """(index in the chunk, the verbatim slice) or None. Whitespace differences are tolerated
    (models re-wrap lines); the returned slice is always the exact chunk text."""
    index = chunk_text.find(quote)
    if index >= 0:
        return index, quote
    words = quote.split()
    if not words:
        return None
    pattern = r"\s+".join(re.escape(w) for w in words)
    match = re.search(pattern, chunk_text)
    return (match.start(), match.group(0)) if match else None


def build_citation(chunk: Chunk, document: DocumentMeta, quote: str) -> Citation | None:
    located = locate_quote(quote.strip(), chunk.text)
    if located is None:
        return None
    index, exact = located
    return Citation(
        chunk_id=chunk.id,
        document_id=document.id,
        doc_title=document.title,
        doc_type=document.doc_type,
        tier=document.tier,
        published_on=document.published_on,
        page=chunk.page,
        char_start=chunk.char_start + index,
        char_end=chunk.char_start + index + len(exact),
        quote=exact,
    )


@dataclass
class WriteOutcome:
    claims: list[Claim]
    missing: list[str]
    rejected: list[DroppedClaim]
    usage: Usage | None = None


def numbered_passages(hits: list[SearchHit]) -> list[NumberedPassage]:
    return [
        NumberedPassage(
            n=i,
            chunk_id=hit.chunk.id,
            text=hit.chunk.text,
            doc_title=hit.document.title,
            tier=int(hit.document.tier),
            published_on=hit.document.published_on,
        )
        for i, hit in enumerate(hits, start=1)
    ]


async def write_claims(
    llm: LLM,
    *,
    question: str,
    sub_questions: list[str],
    hits: list[SearchHit],
    max_claims: int,
    min_quote_chars: int,
) -> WriteOutcome:
    request = WriteRequest(
        question=question,
        sub_questions=sub_questions,
        passages=numbered_passages(hits),
        max_claims=max_claims,
    )
    result, usage = await llm.complete_json(
        task=TASK_WRITE,
        system=prompts.WRITE,
        user=request.model_dump_json(),
        schema=WriteResult,
        stage="write",
    )
    outcome = build_claims(result, hits, min_quote_chars=min_quote_chars)
    outcome.usage = usage
    return outcome


def build_claims(
    result: WriteResult, hits: list[SearchHit], *, min_quote_chars: int
) -> WriteOutcome:
    by_number = dict(enumerate(hits, start=1))
    rejected: list[DroppedClaim] = []
    final_id: dict[str, str] = {}
    claims: list[Claim] = []

    def reject(draft: DraftClaim, reason: str) -> None:
        rejected.append(DroppedClaim(text=draft.text, stage="writer", reason=reason))

    sourced = [d for d in result.claims if d.status == "sourced"]
    inferred = [d for d in result.claims if d.status == "inferred"]
    for draft in sourced:
        citations: list[Citation] = []
        problem = "no evidence given"
        for evidence in draft.evidence:
            hit = by_number.get(evidence.passage)
            if hit is None:
                problem = f"unknown passage {evidence.passage}"
                continue
            if len(evidence.quote.strip()) < min_quote_chars:
                problem = "quote too short"
                continue
            citation = build_citation(hit.chunk, hit.document, evidence.quote)
            if citation is None:
                problem = "quote is not a verbatim span of the passage"
                continue
            if citation not in citations:
                citations.append(citation)
        if not citations or not draft.text.strip():
            reject(draft, problem)
            continue
        final_id[draft.id] = f"c{len(claims) + 1}"
        claims.append(
            Claim(
                id=final_id[draft.id],
                text=draft.text.strip(),
                status=ClaimStatus.SOURCED,
                citations=citations,
            )
        )
    for draft in inferred:
        parents = [final_id[p] for p in draft.derived_from if p in final_id]
        if not draft.derived_from or len(parents) != len(draft.derived_from):
            reject(draft, "derived from a claim that is missing or was rejected")
            continue
        claim_id = f"c{len(claims) + 1}"
        final_id[draft.id] = claim_id
        claims.append(
            Claim(
                id=claim_id,
                text=draft.text.strip(),
                status=ClaimStatus.INFERRED,
                derived_from=parents,
            )
        )
    return WriteOutcome(claims=claims, missing=list(result.missing), rejected=rejected)
