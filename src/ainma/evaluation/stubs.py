"""Deterministic stand ins for the modules that are not merged yet (retrieval, pipeline,
screening, KPI, judge). The report says `stub` wherever one of them produced a number.

They are small lexical baselines, not imitations of the real system: nothing here knows the
ground truth, and no stub ever reports a contradiction or a value it did not read.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from ainma.contracts import (
    TIER_BY_DOCTYPE,
    TIER_WEIGHT,
    AccessContext,
    Answer,
    BuyerCard,
    BuyerProfile,
    Chunk,
    Citation,
    Claim,
    ClaimStatus,
    CriterionResult,
    CriterionStatus,
    DocStatus,
    DocumentMeta,
    Flag,
    MissingInfo,
    ScreeningRequest,
    ScreeningResult,
    Trace,
    Verification,
    VerificationCheck,
)
from ainma.evaluation.metrics.numbers import numbers_covered
from ainma.store import Store

RRF_K = 60
STUB_MODEL = "stub-lexical-v1"
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOP = frozenset(
    {
        *("a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does", "for", "from"),
        *("has", "have", "how", "in", "is", "it", "its", "of", "on", "or", "s", "that", "the"),
        *("their", "to", "was", "were", "what", "when", "which", "who", "whose", "with"),
    }
)
STATUS_FACTOR = {DocStatus.CURRENT: 1.0, DocStatus.SUPERSEDED: 0.2, DocStatus.WITHDRAWN: 0.0}


@dataclass(frozen=True)
class StubHit:
    chunk: Chunk
    score: float


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


def _bm25(query: list[str], docs: list[list[str]], k1: float = 1.2, b: float = 0.75) -> list[float]:
    n = len(docs)
    average = sum(len(d) for d in docs) / n if n else 0.0
    df = Counter(t for d in docs for t in set(d))
    scores: list[float] = []
    for doc in docs:
        counts = Counter(doc)
        total = 0.0
        for term in set(query):
            if counts[term]:
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                norm = (
                    counts[term] * (k1 + 1) / (counts[term] + k1 * (1 - b + b * len(doc) / average))
                )
                total += idf * norm
        scores.append(total)
    return scores


def _trigrams(text: str) -> Counter[str]:
    joined = " ".join(tokens(text))
    return Counter(joined[i : i + 3] for i in range(max(len(joined) - 2, 0)))


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    dot = sum(count * b[gram] for gram, count in a.items())
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return dot / norm if norm else 0.0


def _ranks(scores: Sequence[float]) -> dict[int, int]:
    order = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: (-scores[i], i))
    return {index: rank for rank, index in enumerate(order, start=1)}


def _bigrams(words: list[str]) -> set[tuple[str, str]]:
    return set(zip(words, words[1:], strict=False))


async def stub_search(
    query: str,
    *,
    store: Store,
    access: AccessContext,
    deal_id: str | None,
    system: str,
    top_k: int,
) -> list[StubHit]:
    """A1 BM25, A2 character trigrams, A3 their RRF, A4 adds a coverage and bigram rerank, A5
    weights by tier and status. The candidate set comes from the store, access filter inside."""
    chunks = await store.candidates(access, deal_id=deal_id)
    if not chunks:
        return []
    q = tokens(query)
    docs = [tokens(c.text) for c in chunks]
    bm25 = _bm25(q, docs)
    qgrams = _trigrams(query)
    dense = [_cosine(qgrams, _trigrams(c.text)) for c in chunks]
    scores = bm25 if system == "A1" else dense if system == "A2" else _fuse(bm25, dense)
    if system in {"A4", "A5"}:
        peak = max(scores) or 1.0
        qset, qbi = set(q), _bigrams(q)
        scores = [
            0.5 * s / peak
            + 0.3 * (len(qset & set(d)) / len(qset) if qset else 0.0)
            + 0.2 * (len(qbi & _bigrams(d)) / len(qbi) if qbi else 0.0)
            for s, d in zip(scores, docs, strict=True)
        ]
    if system == "A5":
        documents = {d.id: d for d in await store.list_documents(access, deal_id)}
        scores = [
            s * _source_factor(documents.get(c.document_id), c)
            for s, c in zip(scores, chunks, strict=True)
        ]
    ranked = sorted(range(len(chunks)), key=lambda i: (-scores[i], chunks[i].id))
    return [StubHit(chunks[i], scores[i]) for i in ranked if scores[i] > 0][:top_k]


def _fuse(bm25: list[float], dense: list[float]) -> list[float]:
    one, two = _ranks(bm25), _ranks(dense)
    return [sum(1.0 / (RRF_K + r[i]) for r in (one, two) if i in r) for i in range(len(bm25))]


def _source_factor(document: DocumentMeta | None, chunk: Chunk) -> float:
    tier = TIER_BY_DOCTYPE[chunk.doc_type]
    status = document.status if document is not None else DocStatus.CURRENT
    return TIER_WEIGHT[tier] * STATUS_FACTOR[status]


async def stub_ask(
    question: str,
    *,
    store: Store,
    access: AccessContext,
    deal_id: str | None,
    verifier: bool,
    tau: float | None,
) -> Answer:
    """Quote the best chunks verbatim as sourced claims; abstain below `tau` or without hits."""
    started = time.perf_counter()
    hits = await stub_search(
        question, store=store, access=access, deal_id=deal_id, system="A5", top_k=3
    )
    retrieve_ms = (time.perf_counter() - started) * 1000.0
    best = hits[0].score if hits else None
    answer_id = "stub_" + hashlib.sha256(question.encode()).hexdigest()[:10]
    trace = Trace(
        provider="stub",
        model=STUB_MODEL,
        stage_latency_ms={"retrieve": retrieve_ms},
    )
    if best is None or (tau is not None and best < tau):
        return Answer(
            id=answer_id,
            deal_id=deal_id,
            user_id=access.user_id,
            question=question,
            summary="Not found in the sources available for this deal. No claim is made.",
            claims=[
                Claim(
                    id="c1",
                    text="Not established by the sources.",
                    status=ClaimStatus.MISSING,
                )
            ],
            missing=[MissingInfo(topic=question, reason="not_found")],
            abstained=True,
            abstention_reason="No retrieved passage scored above the support threshold.",
            trace=trace,
        )
    claims: list[Claim] = []
    for number, hit in enumerate(hits, start=1):
        document = await store.get_document(hit.chunk.document_id, access)
        if document is None:
            continue
        citation = Citation(
            chunk_id=hit.chunk.id,
            document_id=document.id,
            doc_title=document.title,
            doc_type=document.doc_type,
            tier=document.tier,
            published_on=document.published_on,
            page=hit.chunk.page,
            char_start=hit.chunk.char_start,
            char_end=hit.chunk.char_end,
            quote=hit.chunk.text,
        )
        flags = [Flag.SUPERSEDED] if document.status is DocStatus.SUPERSEDED else []
        claims.append(
            Claim(
                id=f"c{number}",
                text=hit.chunk.text,
                status=ClaimStatus.SOURCED,
                citations=[citation],
                verification=(
                    Verification(
                        supported=True,
                        checks=[VerificationCheck(name="verbatim_span", passed=True)],
                    )
                    if verifier
                    else None
                ),
                flags=flags,
            )
        )
    return Answer(
        id=answer_id,
        deal_id=deal_id,
        user_id=access.user_id,
        question=question,
        summary=claims[0].text if claims else "",
        claims=claims,
        trace=trace,
    )


async def stub_screen(
    request: ScreeningRequest, buyers: Sequence[BuyerProfile], criteria_keys: Sequence[str]
) -> ScreeningResult:
    """Every criterion unknown: a stub never guesses a status."""
    cards = [
        BuyerCard(
            buyer=buyer,
            stage1_passed=True,
            results=[
                CriterionResult(
                    criterion_key=key,
                    status=CriterionStatus.UNKNOWN,
                    rationale="stub: no evidence retrieved",
                )
                for key in criteria_keys
            ],
        )
        for buyer in buyers
    ]
    return ScreeningResult(deal_id=request.deal_id, request=request, criteria=[], cards=cards)


def stub_judge_label(claim: str, passage: str) -> str:
    """Numbers of the claim must appear in the passage; word overlap decides the rest."""
    claim_words = set(tokens(claim))
    overlap = len(claim_words & set(tokens(passage))) / len(claim_words) if claim_words else 0.0
    numbers_ok = numbers_covered(claim, [passage])
    if numbers_ok and overlap >= 0.8:
        return "supported"
    if overlap >= 0.5:
        return "partial"
    return "unsupported"
