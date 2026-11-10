"""The pipeline of spec section 8: understand, retrieve, write, verify, contradictions, abstain.

`ask` returns an `Answer`; `ask_detailed` also returns the claims that never reached it (rejected
by the writer or dropped by the verifier) so the verifier can be measured. Every answer is
appended to the JSON lines log when `PipelineConfig.answers_log` is set.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

from ainma.contracts import (
    AccessContext,
    Answer,
    Chunk,
    Claim,
    ClaimStatus,
    DocStatus,
    DocumentMeta,
    Flag,
    MissingInfo,
    RankedPassage,
    Trace,
)
from ainma.llm.base import LLM, Usage
from ainma.pipeline import abstain
from ainma.pipeline.config import PipelineConfig
from ainma.pipeline.contradictions import (
    FactIndex,
    collect_claim_facts,
    detect_contradictions,
    extract_facts,
)
from ainma.pipeline.flags import apply_flags
from ainma.pipeline.log import append_answer, entry_for
from ainma.pipeline.schemas import DroppedClaim
from ainma.pipeline.summary import build_summary
from ainma.pipeline.understand import topic_of, understand
from ainma.pipeline.verify import verify_claims
from ainma.pipeline.write import write_claims
from ainma.retrieval.engine import RetrievalEngine, SearchHit
from ainma.store.base import Store

logger = logging.getLogger(__name__)


@dataclass
class AskOutcome:
    answer: Answer
    dropped: list[DroppedClaim]


def _answer_id(question: str, user_id: str, deal_id: str | None, config: PipelineConfig) -> str:
    material = f"{user_id}|{deal_id}|{question}|{_config_hash(config)}"
    return "ans_" + hashlib.sha256(material.encode()).hexdigest()[:12]


def _config_hash(config: PipelineConfig) -> str:
    payload = config.model_dump_json(exclude={"answers_log"})
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _renumber(claims: list[Claim]) -> list[Claim]:
    new_id = {c.id: f"c{i}" for i, c in enumerate(claims, start=1)}
    return [
        c.model_copy(
            update={"id": new_id[c.id], "derived_from": [new_id[p] for p in c.derived_from]}
        )
        for c in claims
    ]


def _round_robin(lists: list[list[SearchHit]], limit: int) -> list[SearchHit]:
    """Best hit of each sub-question first, then the second best, and so on, without repeats."""
    chosen: list[SearchHit] = []
    seen: set[str] = set()
    depth = max((len(items) for items in lists), default=0)
    for position in range(depth):
        for items in lists:
            if position < len(items) and items[position].chunk.id not in seen:
                seen.add(items[position].chunk.id)
                chosen.append(items[position])
    return chosen[:limit]


class _Run:
    """Mutable bookkeeping of one `ask` call: timings and usages."""

    def __init__(self) -> None:
        self.latency: dict[str, float] = {}
        self.usages: list[Usage] = []
        self._started = time.perf_counter()

    def lap(self, stage: str) -> None:
        now = time.perf_counter()
        self.latency[stage] = round((now - self._started) * 1000.0, 3)
        self._started = now

    def trace(self, llm: LLM, retrieved: list[RankedPassage]) -> Trace:
        costs = [u.cost_usd for u in self.usages if u.cost_usd is not None]
        fallbacks = sum(u.fallback_from is not None for u in self.usages)
        provider = llm.provider
        if fallbacks:
            provider = f"{llm.provider} (mock fallback on {fallbacks} call(s))"
        return Trace(
            provider=provider,
            model=llm.model,
            stage_latency_ms=self.latency,
            retrieved=retrieved,
            input_tokens=sum(u.input_tokens for u in self.usages),
            output_tokens=sum(u.output_tokens for u in self.usages),
            cost_usd=sum(costs) if costs else None,
        )


def _missing_claim(index: int, topic: str, reason: str) -> Claim:
    if reason == "withdrawn_only":
        text = f"{topic}: only found in a withdrawn document, which is excluded."
        flags = [Flag.WITHDRAWN]
    else:
        text = f"{topic}: not established by the sources."
        flags = []
    return Claim(id=f"c{index}", text=text, status=ClaimStatus.MISSING, flags=flags)


async def ask_detailed(
    question: str,
    *,
    store: Store,
    access: AccessContext,
    deal_id: str | None,
    llm: LLM,
    config: PipelineConfig | None = None,
    engine: RetrievalEngine | None = None,
) -> AskOutcome:
    cfg = config or PipelineConfig()
    engine = engine or RetrievalEngine()
    run = _Run()
    scope = "this deal" if deal_id else "the general knowledge layer"
    text = question.strip()
    answer_id = _answer_id(text, access.user_id, deal_id, cfg)

    def abstained(
        reason: str,
        topics: list[MissingInfo],
        subs: list[str],
        retrieved: list[RankedPassage],
    ) -> Answer:
        claims = [_missing_claim(i, t.topic, t.reason) for i, t in enumerate(topics, start=1)]
        return Answer(
            id=answer_id,
            deal_id=deal_id,
            user_id=access.user_id,
            question=question,
            sub_questions=subs,
            summary=f"Not found in the sources available for {scope}. No claim is made.",
            claims=claims,
            missing=topics,
            abstained=True,
            abstention_reason=reason,
            trace=run.trace(llm, retrieved),
        )

    async def finish(answer: Answer, dropped: list[DroppedClaim]) -> AskOutcome:
        if cfg.answers_log is not None:
            entry = entry_for(answer, dropped=dropped, config_hash=_config_hash(cfg))
            await append_answer(cfg.answers_log, entry)
        return AskOutcome(answer=answer, dropped=dropped)

    if not text:
        topics = [MissingInfo(topic="the question", reason="not_found")]
        return await finish(abstained(abstain.REASON_EMPTY, topics, [], []), [])

    # 1. understand
    understood, usage = await understand(llm, text)
    run.usages.append(usage)
    subs = [s.strip() for s in understood.sub_questions if s.strip()][: cfg.max_sub_questions]
    subs = subs or [text]
    run.lap("understand")

    # 2. retrieve, per sub-question, through the access filter
    results = [
        await engine.search(sq, store=store, access=access, deal_id=deal_id, config=cfg.retrieval)
        for sq in subs
    ]
    as_of = next((r.as_of for r in results if r.as_of is not None), None)
    documents: dict[str, DocumentMeta] = {}
    chunks: dict[str, Chunk] = {}
    usable: list[list[SearchHit]] = []
    withdrawn: list[list[SearchHit]] = []
    for result in results:
        every = [*result.hits, *result.withdrawn]
        for hit in every:
            documents[hit.document.id] = hit.document
            chunks[hit.chunk.id] = hit.chunk
        usable.append(
            [
                h
                for h in result.hits
                if h.document.status is not DocStatus.WITHDRAWN
                and abstain.support_score(h, cfg.abstain_score) >= cfg.tau
            ]
        )
        withdrawn.append(
            [
                h
                for h in every
                if h.document.status is DocStatus.WITHDRAWN
                and abstain.support_score(h, "relevance") >= cfg.tau
            ]
        )
    seen_ids: set[str] = set()
    retrieved: list[RankedPassage] = []
    for hit in [h for items in [*usable, *withdrawn] for h in items]:
        if hit.chunk.id not in seen_ids:
            seen_ids.add(hit.chunk.id)
            retrieved.append(hit.passage.model_copy(update={"rank": len(retrieved) + 1}))
    run.lap("retrieve")

    def topic_reason(index: int) -> str:
        return "withdrawn_only" if withdrawn[index] and not usable[index] else "not_found"

    if not any(usable):
        reason = abstain.REASON_WITHDRAWN if any(withdrawn) else abstain.REASON_NO_PASSAGE
        topics = [
            MissingInfo(topic=topic_of(sq), reason=topic_reason(i)) for i, sq in enumerate(subs)
        ]
        return await finish(abstained(reason, topics, subs, retrieved), [])

    # 3. write: claims from numbered passages, citations built by code
    passages = _round_robin(usable, cfg.writer_passages)
    written = await write_claims(
        llm,
        question=text,
        sub_questions=subs,
        hits=passages,
        max_claims=cfg.max_claims_per_sub_question,
        min_quote_chars=cfg.min_quote_chars,
    )
    if written.usage is not None:
        run.usages.append(written.usage)
    dropped = list(written.rejected)
    run.lap("write")

    # 4. verify
    claims = written.claims
    if cfg.verifier:
        verified = await verify_claims(
            claims,
            chunks=chunks,
            llm=llm,
            drop_unverified=cfg.drop_unverified,
            concurrency=cfg.judge_concurrency,
        )
        claims = verified.kept
        dropped.extend(verified.dropped)
        run.usages.extend(verified.usages)
    run.lap("verify")

    sub_index = {sq: i for i, sq in enumerate(subs)}
    missing = [
        MissingInfo(
            topic=topic_of(sq),
            reason=topic_reason(sub_index.get(sq, 0)),
        )
        for sq in dict.fromkeys(written.missing)
    ]
    if not any(c.status is ClaimStatus.SOURCED for c in claims):
        reason = abstain.REASON_ALL_DROPPED if dropped else abstain.REASON_NO_CLAIM
        topics = missing or [MissingInfo(topic=topic_of(text), reason="not_found")]
        return await finish(abstained(reason, topics, subs, retrieved), dropped)

    # 5. contradictions, flags
    claims = apply_flags(
        _renumber(claims), documents=documents, ranker=cfg.retrieval.ranker, as_of=as_of
    )
    fact_index = await collect_claim_facts(claims, chunks=chunks, documents=documents, llm=llm)
    run.usages.extend(fact_index.usages)
    subject = await _subject_name(store, access, deal_id)
    contradictions = detect_contradictions(
        fact_index,
        ranker=cfg.retrieval.ranker,
        as_of=as_of,
        tolerance=cfg.contradiction_tolerance,
        subject_name=subject,
    )
    contradicted = {side.claim_id for k in contradictions for side in k.sides}
    claims = [
        c.model_copy(update={"flags": [*c.flags, Flag.CONTRADICTED]}) if c.id in contradicted else c
        for c in claims
    ]
    claims = await _flag_withdrawn(claims, withdrawn, fact_index, llm, run)
    run.lap("contradictions")

    # 6. assemble
    answer_claims = [
        *claims,
        *(
            _missing_claim(len(claims) + i, m.topic, m.reason)
            for i, m in enumerate(missing, start=1)
        ),
    ]
    answer = Answer(
        id=answer_id,
        deal_id=deal_id,
        user_id=access.user_id,
        question=question,
        sub_questions=subs,
        summary=build_summary(answer_claims, contradictions, missing, scope=scope),
        claims=answer_claims,
        contradictions=contradictions,
        missing=missing,
        trace=run.trace(llm, retrieved),
    )
    return await finish(answer, dropped)


async def _subject_name(store: Store, access: AccessContext, deal_id: str | None) -> str:
    if deal_id is None:
        return "General"
    deal = await store.get_deal(deal_id, access)
    return deal.name if deal else deal_id


async def _flag_withdrawn(
    claims: list[Claim],
    withdrawn: list[list[SearchHit]],
    index: FactIndex,
    llm: LLM,
    run: _Run,
) -> list[Claim]:
    """`Flag.WITHDRAWN` on a claim means a withdrawn document spoke to the same fact (metric and
    period) and was excluded. A withdrawn document is never a citation."""
    hits = {h.chunk.id: h for items in withdrawn for h in items}
    if not hits:
        return claims
    keys: set[tuple[str, str | None]] = set()
    for hit in hits.values():
        facts, usage = await extract_facts(llm, hit.chunk.text)
        run.usages.append(usage)
        keys.update((f.metric, f.period) for f in facts)
    flagged = {e.claim_id for e in index.entries if (e.fact.metric, e.fact.period) in keys}
    return [
        c.model_copy(update={"flags": [*c.flags, Flag.WITHDRAWN]}) if c.id in flagged else c
        for c in claims
    ]


async def ask(
    question: str,
    *,
    store: Store,
    access: AccessContext,
    deal_id: str | None,
    llm: LLM,
    config: PipelineConfig | None = None,
    engine: RetrievalEngine | None = None,
) -> Answer:
    """Answer `question` for the user of `access` in `deal_id` (or the general layer).

    Pass one `RetrievalEngine` across calls to reuse the fitted indexes (hundreds of queries).
    """
    outcome = await ask_detailed(
        question,
        store=store,
        access=access,
        deal_id=deal_id,
        llm=llm,
        config=config,
        engine=engine,
    )
    return outcome.answer
