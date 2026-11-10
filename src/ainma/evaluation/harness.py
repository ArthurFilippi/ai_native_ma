"""Run every measurement of the evaluation plan for one seed and keep the per unit raw results.

Nothing here computes a table: `aggregate` pools the units of all seeds and puts intervals on
them. The splits follow eval plan section 2: `tau` is chosen on the dev queries only, frozen,
and every reported number comes from the test split.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from ainma.contracts import Answer, ClaimStatus, Flag, ScreeningFilters, ScreeningRequest
from ainma.evaluation.adapter import Adapter, RankedChunk, Sweep
from ainma.evaluation.groundtruth import TruthBundle
from ainma.evaluation.metrics.abstention import NO_EVIDENCE, choose_tau
from ainma.evaluation.metrics.citation import (
    CitedClaim,
    GoldFact,
    QuotedCitation,
    citation_counts,
    claim_is_unsupported,
)
from ainma.evaluation.metrics.kpi import KpiOutcome, quote_contains_value
from ainma.evaluation.metrics.retrieval import (
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from ainma.evaluation.metrics.screening import ranking_agreement, true_scores
from ainma.store import Store
from ainma.truth import Fact, Query, split_of

SYSTEMS = ("A1", "A2", "A3", "A4", "A5")
RETRIEVAL_METRICS = ("ndcg@10", "recall@5", "recall@10", "recall@30", "mrr")
TOP_K = 30
TARGET_FALSE_ABSTENTION = 0.10
EvalSplit = Literal["dev", "test", "both"]
FLAG_FOR = {"flag_superseded": Flag.SUPERSEDED, "flag_withdrawn": Flag.WITHDRAWN}


def in_split(split: EvalSplit, key: str) -> bool:
    """Whether the unit with id `key` belongs to the selected split (`both` keeps everything)."""
    return split == "both" or split_of(key) == split


MetricTable = dict[str, dict[str, list[float | None]]]  # metric -> system or variant -> per query


@dataclass
class CitationUnits:
    """Per answerable test query counts for one verifier setting."""

    n_claims: list[int] = field(default_factory=list)
    n_correct: list[int] = field(default_factory=list)
    n_facts: list[int] = field(default_factory=list)
    n_covered: list[int] = field(default_factory=list)
    n_unsupported: list[int] = field(default_factory=list)


@dataclass
class AbstentionUnits:
    tau: float  # the threshold applied to the test split: the frozen one when there is one
    target: float
    dev_tau: float = NO_EVIDENCE  # calibrated on the dev queries of this seed alone (extra table)
    dev_answerable: list[float | None] = field(default_factory=list)
    dev_unanswerable: list[float | None] = field(default_factory=list)
    test_answerable: list[float | None] = field(default_factory=list)
    test_unanswerable: list[float | None] = field(default_factory=list)
    test_unanswerable_hard: list[bool] = field(default_factory=list)
    e2e_answerable: list[bool] = field(default_factory=list)  # abstained, at the frozen tau
    e2e_unanswerable: list[bool] = field(default_factory=list)


@dataclass
class ContradictionUnits:
    planted: list[bool] = field(default_factory=list)
    controls: list[bool] = field(default_factory=list)
    both_sides_cited: list[bool] = field(default_factory=list)  # among detected planted pairs
    stronger_agrees: list[bool] = field(default_factory=list)  # among detected, truth has a side
    flag_outcomes: list[str] = field(default_factory=list)  # superseded and withdrawn cases
    stale_flagged: list[bool] = field(default_factory=list)


@dataclass
class VerifierUnits:
    truth: list[str] = field(default_factory=list)
    judge: list[str] = field(default_factory=list)
    flagged: list[bool] = field(default_factory=list)
    perturbation: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KpiCell:
    kpi_id: str
    period: str
    kind: str
    outcome: KpiOutcome


@dataclass
class TimingUnits:
    search_ms: dict[str, list[float]] = field(default_factory=dict)  # system -> per query
    stage_ms: dict[str, list[float]] = field(default_factory=dict)  # trace stage -> per ask
    ask_wall_ms: list[float] = field(default_factory=list)
    cost_usd: list[float | None] = field(default_factory=list)
    input_tokens: list[int] = field(default_factory=list)
    output_tokens: list[int] = field(default_factory=list)


@dataclass
class SeedResult:
    label: str
    params: dict[str, object]
    missing_truth_files: list[str]
    query_ids: list[str] = field(default_factory=list)
    clusters: list[str] = field(default_factory=list)
    retrieval: MetricTable = field(default_factory=dict)
    sweeps: dict[str, dict[str, MetricTable]] = field(default_factory=dict)  # name -> variant
    citation: dict[str, CitationUnits] = field(default_factory=dict)  # "on" | "off"
    abstention: AbstentionUnits | None = None
    contradiction: ContradictionUnits = field(default_factory=ContradictionUnits)
    verifier: VerifierUnits = field(default_factory=VerifierUnits)
    kpi: list[KpiCell] = field(default_factory=list)
    screening: list[tuple[str, str]] = field(default_factory=list)
    # per deal: Spearman of the system order against the truth score, with the rank rule of the
    # product (floor of the score range, D86) and with the previous rule (score, then coverage)
    screening_rank: list[tuple[float | None, float | None]] = field(default_factory=list)
    timing: TimingUnits = field(default_factory=TimingUnits)
    counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Timed:
    answer: Answer
    wall_ms: float


class Asker:
    """Runs `ask` once per distinct (question, deal, verifier) and remembers the answer."""

    def __init__(self, adapter: Adapter, truth: TruthBundle, tau: float) -> None:
        self._adapter = adapter
        self._access = truth.access()
        self._tau = None if tau == NO_EVIDENCE else tau
        self._cache: dict[tuple[str, str | None, bool], Timed] = {}

    async def ask(self, question: str, deal_id: str | None, *, verifier: bool = True) -> Timed:
        key = (question, deal_id, verifier)
        if key not in self._cache:
            started = time.perf_counter()
            answer = await self._adapter.ask(
                question, access=self._access, deal_id=deal_id, verifier=verifier, tau=self._tau
            )
            self._cache[key] = Timed(answer, (time.perf_counter() - started) * 1000.0)
        return self._cache[key]


def gold_facts(query: Query, facts: dict[str, Fact]) -> list[GoldFact]:
    out: list[GoldFact] = []
    for fact_id in query.gold_fact_ids:
        fact = facts.get(fact_id)
        if fact is None:
            continue
        keywords = tuple(fact.keywords) or (fact.metric.replace("_", " "), fact.period)
        out.append(GoldFact(fact.id, fact.value, keywords, frozenset(fact.support_chunk_ids)))
    return out


def top_score(ranked: list[RankedChunk]) -> float | None:
    """Best support score of a ranking: what the pipeline compares with tau."""
    return max(r.support for r in ranked) if ranked else None


def retrieval_metrics(
    ranked: list[RankedChunk], relevance: dict[str, int]
) -> dict[str, float | None]:
    ids = [r.chunk_id for r in ranked]
    return {
        "ndcg@10": ndcg_at_k(ids, relevance, 10),
        "recall@5": recall_at_k(ids, relevance, 5),
        "recall@10": recall_at_k(ids, relevance, 10),
        "recall@30": recall_at_k(ids, relevance, 30),
        "mrr": reciprocal_rank(ids, relevance),
    }


async def _retrieval(
    result: SeedResult,
    adapter: Adapter,
    truth: TruthBundle,
    test_queries: list[Query],
    sweeps: list[Sweep],
) -> dict[str, list[list[RankedChunk]]]:
    """Systems A1 to A5 on the test queries, then the A5 sweeps. Returns the A5 rankings."""
    access = truth.access()
    facts = truth.facts_by_id()
    result.query_ids = [q.id for q in test_queries]
    result.clusters = [
        facts[q.gold_fact_ids[0]].document_id if q.gold_fact_ids[0] in facts else q.id
        for q in test_queries
    ]
    result.retrieval = {m: {} for m in RETRIEVAL_METRICS}
    rankings: dict[str, list[list[RankedChunk]]] = {}
    for system in SYSTEMS:
        per_query: list[list[float | None]] = []
        runs: list[list[RankedChunk]] = []
        latencies: list[float] = []
        for query in test_queries:
            started = time.perf_counter()
            ranked = await adapter.search(
                query.text, access=access, deal_id=query.deal_id, system=system, top_k=TOP_K
            )
            latencies.append((time.perf_counter() - started) * 1000.0)
            runs.append(ranked)
            metrics = retrieval_metrics(ranked, query.relevance)
            per_query.append([metrics[m] for m in RETRIEVAL_METRICS])
        for column, metric in enumerate(RETRIEVAL_METRICS):
            result.retrieval[metric][system] = [row[column] for row in per_query]
        result.timing.search_ms[system] = latencies
        rankings[system] = runs
    for sweep in sweeps:
        result.sweeps[sweep.name] = {}
        for label, overrides in sweep.variants:
            table: MetricTable = {m: {} for m in RETRIEVAL_METRICS}
            rows: list[dict[str, float | None]] = []
            for query in test_queries:
                ranked = await adapter.search(
                    query.text,
                    access=access,
                    deal_id=query.deal_id,
                    system="A5",
                    top_k=TOP_K,
                    overrides=overrides,
                )
                rows.append(retrieval_metrics(ranked, query.relevance))
            for metric in RETRIEVAL_METRICS:
                table[metric][label] = [row[metric] for row in rows]
            result.sweeps[sweep.name][label] = table
    return rankings


async def _chunk_text(
    store: Store, truth: TruthBundle, cache: dict[str, str], chunk_id: str
) -> str:
    if chunk_id not in cache:
        chunk = await store.get_chunk(chunk_id, truth.access())
        cache[chunk_id] = chunk.text if chunk is not None else ""
    return cache[chunk_id]


async def _citations(
    result: SeedResult,
    asker: Asker,
    store: Store,
    truth: TruthBundle,
    test_queries: list[Query],
    texts: dict[str, str],
) -> None:
    facts = truth.facts_by_id()
    for setting, verifier in (("on", True), ("off", False)):
        units = CitationUnits()
        for query in test_queries:
            timed = await asker.ask(query.text, query.deal_id, verifier=verifier)
            sourced = [c for c in timed.answer.claims if c.status is ClaimStatus.SOURCED]
            claims = [CitedClaim(c.text, tuple(x.chunk_id for x in c.citations)) for c in sourced]
            counts = citation_counts(claims, gold_facts(query, facts))
            unsupported = 0
            for claim in sourced:
                quoted = [
                    QuotedCitation(x.quote, await _chunk_text(store, truth, texts, x.chunk_id))
                    for x in claim.citations
                ]
                unsupported += int(claim_is_unsupported(claim.text, quoted))
            units.n_claims.append(counts.n_claims)
            units.n_correct.append(counts.n_correct)
            units.n_facts.append(counts.n_facts)
            units.n_covered.append(counts.n_covered)
            units.n_unsupported.append(unsupported)
            if verifier:
                _record_trace(result, timed)
        result.citation[setting] = units


def _record_trace(result: SeedResult, timed: Timed) -> None:
    trace = timed.answer.trace
    timing = result.timing
    for stage, ms in sorted(trace.stage_latency_ms.items()):
        timing.stage_ms.setdefault(stage, []).append(ms)
    timing.ask_wall_ms.append(timed.wall_ms)
    timing.cost_usd.append(trace.cost_usd)
    timing.input_tokens.append(trace.input_tokens)
    timing.output_tokens.append(trace.output_tokens)


async def _abstention(
    result: SeedResult,
    adapter: Adapter,
    truth: TruthBundle,
    test_queries: list[Query],
    a5_test: list[list[RankedChunk]],
    split: EvalSplit,
    frozen_tau: float | None,
) -> AbstentionUnits:
    access = truth.access()
    dev_queries = [q for q in truth.queries if split_of(q.id) == "dev"]
    units_scores = AbstentionUnits(tau=NO_EVIDENCE, target=TARGET_FALSE_ABSTENTION)

    async def score(text: str, deal_id: str | None) -> float | None:
        return top_score(
            await adapter.search(text, access=access, deal_id=deal_id, system="A5", top_k=TOP_K)
        )

    units_scores.dev_answerable = await dev_support_scores(adapter, truth)
    units_scores.test_answerable = [top_score(r) for r in a5_test]
    for item in truth.unanswerable:
        value = await score(item.text, item.deal_id)
        if split_of(item.id) == "dev":
            units_scores.dev_unanswerable.append(value)
        if in_split(split, item.id):
            units_scores.test_unanswerable.append(value)
            units_scores.test_unanswerable_hard.append(item.hard)
    if units_scores.dev_answerable:
        units_scores.dev_tau = choose_tau(units_scores.dev_answerable, TARGET_FALSE_ABSTENTION)
    # one frozen threshold for every seed, the one the API and the demo use; the per seed
    # calibration is kept as a table so drift is visible
    units_scores.tau = units_scores.dev_tau if frozen_tau is None else frozen_tau
    result.counts["dev_answerable"] = len(dev_queries)
    return units_scores


async def dev_support_scores(adapter: Adapter, truth: TruthBundle) -> list[float | None]:
    """Best support score of every dev answerable query of a seed (what `tau` is chosen on)."""
    access = truth.access()
    return [
        top_score(
            await adapter.search(q.text, access=access, deal_id=q.deal_id, system="A5", top_k=TOP_K)
        )
        for q in truth.queries
        if split_of(q.id) == "dev"
    ]


async def _e2e_abstention(
    units: AbstentionUnits, asker: Asker, truth: TruthBundle, split: EvalSplit
) -> None:
    for query in (q for q in truth.queries if in_split(split, q.id)):
        timed = await asker.ask(query.text, query.deal_id)
        units.e2e_answerable.append(timed.answer.abstained)
    for item in (u for u in truth.unanswerable if in_split(split, u.id)):
        timed = await asker.ask(item.text, item.deal_id)
        units.e2e_unanswerable.append(timed.answer.abstained)


def _docs_of_contradiction(answer: Answer) -> list[tuple[set[str], int, bool, int | None]]:
    """Per contradiction: documents cited, number of sides, all sides cited, stronger side docs."""
    rows: list[tuple[set[str], int, bool, int | None]] = []
    for contradiction in answer.contradictions:
        docs = {c.document_id for side in contradiction.sides for c in side.citations}
        cited = all(side.citations for side in contradiction.sides)
        rows.append((docs, len(contradiction.sides), cited, contradiction.stronger_side))
    return rows


async def _contradictions(
    result: SeedResult, asker: Asker, truth: TruthBundle, split: EvalSplit
) -> None:
    queries = truth.queries_by_id()
    facts = truth.facts_by_id()
    units = result.contradiction
    for case in truth.contradictions:
        # planted cases are split by the hash of their own id, like every other truth unit
        if not in_split(split, case.id):
            continue
        question = (
            queries[case.query_id].text if case.query_id in queries else f"What is {case.subject}?"
        )
        answer = (await asker.ask(question, case.deal_id)).answer
        wanted = set(case.document_ids)
        matched = [
            (index, row)
            for index, row in enumerate(_docs_of_contradiction(answer))
            if len(row[0] & wanted) >= 2
        ]
        if case.kind == "contradiction":
            units.planted.append(bool(matched))
            if matched:
                index, (_, _, cited, stronger) = matched[0]
                units.both_sides_cited.append(cited)
                if case.stronger_document_id is not None and stronger is not None:
                    side = answer.contradictions[index].sides[stronger]
                    units.stronger_agrees.append(
                        case.stronger_document_id in {c.document_id for c in side.citations}
                    )
        elif case.kind == "consistent_control":
            units.controls.append(bool(matched))
        else:
            expected = FLAG_FOR[case.expected]
            citing = [
                claim
                for claim in answer.claims
                if wanted & {c.document_id for c in claim.citations}
            ]
            if matched:
                units.flag_outcomes.append("contradicted_instead")
            elif any(expected in claim.flags for claim in citing):
                units.flag_outcomes.append("flagged")
            elif citing:
                units.flag_outcomes.append("unflagged")
            else:
                units.flag_outcomes.append("not_surfaced")
    for stale in truth.stale:
        if not in_split(split, stale.id):
            continue
        query = queries.get(stale.query_id)
        fact = facts.get(stale.fact_id)
        if query is None or fact is None:
            continue
        answer = (await asker.ask(query.text, query.deal_id)).answer
        support = set(fact.support_chunk_ids)
        flagged = any(
            Flag.STALE in claim.flags and support & {c.chunk_id for c in claim.citations}
            for claim in answer.claims
        ) or any(m.reason == "stale_only" for m in answer.missing)
        units.stale_flagged.append(flagged)


async def _verifier(
    result: SeedResult,
    adapter: Adapter,
    store: Store,
    truth: TruthBundle,
    texts: dict[str, str],
    split: EvalSplit,
) -> None:
    units = result.verifier
    for label in truth.judge_labels:
        if split != "both" and label.split != split:
            continue
        passage = await _chunk_text(store, truth, texts, label.chunk_id)
        verdict = await adapter.judge(label.claim, passage, label.quote)
        units.truth.append(label.label)
        units.judge.append(verdict.label)
        units.flagged.append(verdict.label != "supported" or not verdict.checks_passed)
        units.perturbation.append(label.perturbation)


async def _kpis(result: SeedResult, adapter: Adapter, truth: TruthBundle) -> None:
    access = truth.access()
    for deal_id in sorted({row.deal_id for row in truth.kpi_truth}):
        rows = [row for row in truth.kpi_truth if row.deal_id == deal_id]
        periods = sorted({row.period for row in rows})
        values = await adapter.kpis(deal_id, access=access, periods=periods)
        found = {(v.kpi_id, v.period): v for v in values}
        for row in rows:
            value = found.get((row.kpi_id, row.period))
            number = value.value if value is not None else None
            quote_valid: bool | None = None
            if value is not None and value.status == "sourced" and number is not None:
                quote_valid = any(quote_contains_value(c.quote, number) for c in value.citations)
            result.kpi.append(
                KpiCell(
                    row.kpi_id, row.period, row.kind, KpiOutcome(row.value, number, quote_valid)
                )
            )


async def _screening(result: SeedResult, adapter: Adapter, truth: TruthBundle) -> None:
    """Screen each deal the way the product does: no typed filter, so stage 1 is prefilled from
    the deal record (its region and value, D87), every buyer that passes stage 1 reaches stage 2,
    and the simulated news feed is filed in the deal space first (60 acquisitions exist only
    there). The buyer truth for geography and size is defined against the same region and the
    same size range (EV to 60 x EV), see D80.
    """
    access = truth.access()
    filters = ScreeningFilters()
    for deal_id in sorted({row.deal_id for row in truth.buyer_truth}):
        if truth.seed_dir is not None:
            await adapter.ingest_news(deal_id, access=access, seed_dir=truth.seed_dir)
        request = ScreeningRequest(deal_id=deal_id, filters=filters, stage2_top_n=50)
        screened = await adapter.screen(request, access=access)
        statuses = {
            (card.buyer.id, r.criterion_key): r.status.value
            for card in screened.cards
            for r in card.results
        }
        truth_statuses: dict[str, dict[str, str]] = {}
        for row in truth.buyer_truth:
            if row.deal_id == deal_id:
                predicted = statuses.get((row.buyer_id, row.criterion_key), "unknown")
                result.screening.append((row.status.value, predicted))
                truth_statuses.setdefault(row.buyer_id, {})[row.criterion_key] = row.status.value
        weights = {c.key: c.weight for c in screened.criteria}
        target = true_scores(truth_statuses, weights)
        ranked = [c for c in screened.cards if c.rank is not None]
        legacy = sorted(
            ranked,
            key=lambda c: (
                bool(c.dealbreakers),
                c.score is None,
                -(c.score or 0.0),
                -c.coverage,
                c.buyer.id,
            ),
        )
        result.screening_rank.append(
            (
                ranking_agreement([c.buyer.id for c in ranked], target),
                ranking_agreement([c.buyer.id for c in legacy], target),
            )
        )


async def evaluate_seed(
    label: str,
    *,
    store: Store,
    truth: TruthBundle,
    adapter: Adapter,
    run_sweeps: bool = True,
    split: EvalSplit = "test",
    frozen_tau: float | None = None,
) -> SeedResult:
    """All measurements for one seed. `store` holds the loaded corpus of that seed.

    `split` selects the units that are measured. The abstention threshold is `frozen_tau` (the
    pipeline's `DEFAULT_TAU`, chosen once on the pooled dev queries of all seeds); without one
    (stubs, smoke) it is calibrated on the dev queries of the seed. On `dev` and `both` it is
    applied to queries it was chosen on (in sample, for development only).
    """
    params: dict[str, object] = truth.params.model_dump() if truth.params is not None else {}
    result = SeedResult(label=label, params=params, missing_truth_files=truth.missing_files)
    test_queries = [q for q in truth.queries if in_split(split, q.id)]
    sweeps = adapter.sweeps() if run_sweeps else []
    rankings = await _retrieval(result, adapter, truth, test_queries, sweeps)
    abstention = await _abstention(
        result, adapter, truth, test_queries, rankings["A5"], split, frozen_tau
    )
    asker = Asker(adapter, truth, abstention.tau)
    texts: dict[str, str] = {}
    await _citations(result, asker, store, truth, test_queries, texts)
    await _e2e_abstention(abstention, asker, truth, split)
    result.abstention = abstention
    await _contradictions(result, asker, truth, split)
    await _verifier(result, adapter, store, truth, texts, split)
    await _kpis(result, adapter, truth)
    await _screening(result, adapter, truth)
    result.counts.update(
        {
            "answerable_test": len(test_queries),
            "unanswerable_test": len(abstention.test_unanswerable),
            "adversarial_test": len(result.verifier.truth),
        }
    )
    return result
