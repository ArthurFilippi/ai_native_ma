"""The pipeline of spec section 8: understand, retrieve, write, verify, contradictions, abstain.

`ask` returns an `Answer`; `ask_detailed` also returns the claims that never reached it (rejected
by the writer or dropped by the verifier) so the verifier can be measured. Every answer is
appended to the JSON lines log when `PipelineConfig.answers_log` is set.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Sequence
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
    MarketEvent,
    MissingInfo,
    RankedPassage,
    Trace,
)
from ainma.factbase import FactBase
from ainma.llm.base import LLM, Usage
from ainma.pipeline import abstain
from ainma.pipeline.confidence import answer_confidence
from ainma.pipeline.config import PipelineConfig
from ainma.pipeline.contradictions import (
    FactIndex,
    collect_claim_facts,
    detect_contradictions,
    extract_facts,
)
from ainma.pipeline.events_route import event_claims, route_market
from ainma.pipeline.flags import apply_flags
from ainma.pipeline.log import append_answer, entry_for
from ainma.pipeline.rules import subject_of
from ainma.pipeline.schemas import DroppedClaim
from ainma.pipeline.structured import Routed, asks_for_change, route_request, routed_claims
from ainma.pipeline.summary import build_summary
from ainma.pipeline.understand import topic_of, understand
from ainma.pipeline.verify import verify_claims
from ainma.pipeline.write import WriteOutcome, write_claims
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

    def degraded_reason(self) -> str | None:
        """Why the answer is degraded: the mock answered for a failed live call (D88)."""
        failed = sorted({u.fallback_from for u in self.usages if u.fallback_from is not None})
        if not failed:
            return None
        n = sum(u.fallback_from is not None for u in self.usages)
        return (
            f"{', '.join(failed)} failed on {n} call(s); the offline mock (rules, not a model) "
            "answered them. Treat this answer as degraded."
        )

    def trace(self, llm: LLM, retrieved: list[RankedPassage], judge: LLM | None = None) -> Trace:
        costs = [u.cost_usd for u in self.usages if u.cost_usd is not None]
        fallbacks = sum(u.fallback_from is not None for u in self.usages)
        provider = llm.provider
        if fallbacks:
            provider = f"{llm.provider} (mock fallback on {fallbacks} call(s))"
        judge = judge or llm
        return Trace(
            provider=provider,
            model=llm.model,
            judge_provider=judge.provider,
            judge_model=judge.model,
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
    judge_llm: LLM | None = None,
    factbase: FactBase | None = None,
    events: Sequence[MarketEvent] | None = None,
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
            trace=run.trace(llm, retrieved, judge_llm),
            degraded=run.degraded_reason() is not None,
            degraded_reason=run.degraded_reason(),
        )

    async def finish(answer: Answer, dropped: list[DroppedClaim]) -> AskOutcome:
        level, why = answer_confidence(answer)
        answer = answer.model_copy(update={"confidence": level, "confidence_reason": why})
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

    # 1b. route: a sub-question asking for one keyed value is answered by the structured base
    routed: dict[int, Routed] = {}
    if factbase is not None and cfg.structured_routing and not asks_for_change(text):
        for i, sq in enumerate(subs):
            record = route_request(sq, factbase, access=access, deal_id=deal_id)
            if record is None:
                continue
            claims_of = await routed_claims(record, store=store, access=access, start=100 * (i + 1))
            if claims_of is not None:
                routed[i] = claims_of
    if events and cfg.event_routing and not routed:
        matched = route_market(text, events)
        if matched:
            event_routed = await event_claims(matched, store=store, access=access, start=900)
            if event_routed is not None:
                # the whole question is about the events: every sub-question is answered by them
                routed = {
                    i: (event_routed if i == 0 else Routed(None, [])) for i in range(len(subs))
                }

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
    for index, result in enumerate(results):
        every = [*result.hits, *result.superseded, *result.withdrawn]
        for hit in every:
            documents[hit.document.id] = hit.document
            chunks[hit.chunk.id] = hit.chunk
        about = [
            h
            for h in [*result.hits, *result.superseded]
            if h.document.status is not DocStatus.WITHDRAWN
            and abstain.about_entity(h, cfg.entity_gate)
        ]
        # `tau` decides whether the sources speak to the question at all (their best passage);
        # the weaker passages around a convincing one still reach the writer, because they are
        # the second opinion that makes a disagreement visible (a press article next to a CIM)
        speaks = index not in routed and any(
            abstain.support_score(h, cfg.abstain_score) >= cfg.tau for h in about
        )
        usable.append(
            [h for h in about if abstain.support_score(h, "relevance") >= cfg.passage_min]
            if speaks
            else []
        )
        withdrawn.append(
            [
                h
                for h in every
                if h.document.status is DocStatus.WITHDRAWN
                and abstain.about_entity(h, cfg.entity_gate)
                and abstain.support_score(h, "relevance") >= cfg.tau
            ]
        )
    for item in routed.values():
        chunks.update(item.chunks)
        documents.update(item.documents)
    seen_ids: set[str] = set()
    retrieved: list[RankedPassage] = []
    for hit in [h for items in [*usable, *withdrawn] for h in items]:
        if hit.chunk.id not in seen_ids:
            seen_ids.add(hit.chunk.id)
            retrieved.append(hit.passage.model_copy(update={"rank": len(retrieved) + 1}))
    run.lap("retrieve")

    def topic_reason(index: int) -> str:
        return "withdrawn_only" if withdrawn[index] and not usable[index] else "not_found"

    if not any(usable) and not routed:
        reason = abstain.REASON_WITHDRAWN if any(withdrawn) else abstain.REASON_NO_PASSAGE
        topics = [
            MissingInfo(topic=topic_of(sq), reason=topic_reason(i)) for i, sq in enumerate(subs)
        ]
        return await finish(abstained(reason, topics, subs, retrieved), [])

    # 3. write: claims from numbered passages, citations built by code
    passages = _round_robin(
        [abstain.writer_window(items, cfg.writer_passages) for items in usable],
        cfg.writer_passages,
    )
    text_subs = [sq for i, sq in enumerate(subs) if i not in routed]
    if passages and text_subs:
        written = await write_claims(
            llm,
            question=text,
            sub_questions=text_subs,
            hits=passages,
            max_claims=cfg.max_claims_per_sub_question,
            min_quote_chars=cfg.min_quote_chars,
        )
    else:
        written = WriteOutcome(
            claims=[],
            missing=[sq for i, sq in enumerate(text_subs) if not usable[subs.index(sq)]],
            rejected=[],
        )
    if written.usage is not None:
        run.usages.append(written.usage)
    dropped = list(written.rejected)
    run.lap("write")

    # 4. verify (structured claims go through the same checks as text claims)
    claims = [c for item in routed.values() for c in item.claims] + written.claims
    if cfg.verifier:
        verified = await verify_claims(
            claims,
            chunks=chunks,
            llm=judge_llm or llm,
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
    subject = await _subject_name(store, access, deal_id, text)
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
        trace=run.trace(llm, retrieved, judge_llm),
        degraded=run.degraded_reason() is not None,
        degraded_reason=run.degraded_reason(),
    )
    return await finish(answer, dropped)


async def _subject_name(
    store: Store, access: AccessContext, deal_id: str | None, question: str
) -> str:
    """Who a contradiction is about: the deal inside a deal, else the entity the question names
    (a buyer), never a placeholder."""
    if deal_id is None:
        return subject_of(question) or "General"
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
    judge_llm: LLM | None = None,
    factbase: FactBase | None = None,
    events: Sequence[MarketEvent] | None = None,
) -> Answer:
    """Answer `question` for the user of `access` in `deal_id` (or the general layer).

    Pass one `RetrievalEngine` across calls to reuse the fitted indexes (hundreds of queries).
    `judge_llm` judges the claims when given (a model distinct from the writer, D88).
    `factbase` answers the sub-questions that ask for one keyed value (D92).
    """
    outcome = await ask_detailed(
        question,
        store=store,
        access=access,
        deal_id=deal_id,
        llm=llm,
        config=config,
        engine=engine,
        judge_llm=judge_llm,
        factbase=factbase,
        events=events,
    )
    return outcome.answer
