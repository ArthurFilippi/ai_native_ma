"""The harness wiring, checked against an oracle system and against the labelled stubs."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

import pytest

from ainma.contracts import (
    AccessContext,
    Answer,
    Citation,
    Claim,
    ClaimStatus,
    Contradiction,
    ContradictionSide,
    Flag,
    KpiValue,
    MissingInfo,
    ScreeningRequest,
    ScreeningResult,
    Trace,
)
from ainma.evaluation.adapter import Adapter, JudgeVerdict, RankedChunk
from ainma.evaluation.aggregate import summarise
from ainma.evaluation.groundtruth import TruthBundle
from ainma.evaluation.harness import SYSTEMS, evaluate_seed
from ainma.evaluation.smoke import load_smoke_store, smoke_truth
from ainma.llm import build_mock_llm
from ainma.store import Store
from ainma.truth import split_of


@pytest.fixture
async def smoke_store() -> AsyncIterator[Store]:
    store = await load_smoke_store()
    yield store
    await store.close()


class OracleAdapter(Adapter):
    """Knows the truth and answers perfectly: it proves the harness scores a perfect system as
    perfect, which no stub can."""

    def __init__(self, store: Store, truth: TruthBundle) -> None:
        super().__init__(store=store, llm=build_mock_llm(), use_real=False)
        self._truth = truth
        self._by_text = {q.text: q for q in truth.queries}
        self._unanswerable = {u.text for u in truth.unanswerable}

    async def search(
        self,
        query: str,
        *,
        access: AccessContext,
        deal_id: str | None,
        system: str,
        top_k: int = 30,
        overrides: Mapping[str, Any] | None = None,
    ) -> list[RankedChunk]:
        query_row = self._by_text.get(query)
        if query_row is None:
            return [RankedChunk("doc_playbook_p1_01", 0.01, 0.01)]
        ordered = sorted(query_row.relevance.items(), key=lambda kv: (-kv[1], kv[0]))
        return [
            RankedChunk(chunk_id, 0.9 - 0.01 * i, 0.9 - 0.01 * i)
            for i, (chunk_id, _) in enumerate(ordered)
        ]

    async def _citation(self, chunk_id: str) -> Citation:
        chunk = await self._store.get_chunk(chunk_id, self._truth.access())
        assert chunk is not None
        document = await self._store.get_document(chunk.document_id, self._truth.access())
        assert document is not None
        return Citation(
            chunk_id=chunk.id,
            document_id=document.id,
            doc_title=document.title,
            doc_type=document.doc_type,
            tier=document.tier,
            page=chunk.page,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            quote=chunk.text,
        )

    async def ask(
        self,
        question: str,
        *,
        access: AccessContext,
        deal_id: str | None,
        verifier: bool = True,
        tau: float | None = None,
    ) -> Answer:
        trace = Trace(provider="oracle", model="oracle", stage_latency_ms={"write": 1.0})
        base = {"id": "a", "deal_id": deal_id, "user_id": "u", "question": question, "trace": trace}
        query = self._by_text.get(question)
        if query is None:
            return Answer(
                summary="not found",
                abstained=True,
                claims=[Claim(id="c0", text="missing", status=ClaimStatus.MISSING)],
                missing=[MissingInfo(topic=question, reason="not_found")],
                **base,
            )
        facts = self._truth.facts_by_id()
        claims: list[Claim] = []
        for number, fact_id in enumerate(query.gold_fact_ids, start=1):
            fact = facts[fact_id]
            citation = await self._citation(fact.support_chunk_ids[0])
            claims.append(
                Claim(
                    id=f"c{number}",
                    text=citation.quote,
                    status=ClaimStatus.SOURCED,
                    citations=[citation],
                    flags=[Flag.WITHDRAWN] if fact.document_id == "doc_pr_orig" else [],
                )
            )
        contradictions: list[Contradiction] = []
        for case in self._truth.contradictions:
            if case.query_id == query.id and case.kind == "contradiction":
                sides = [
                    ContradictionSide(
                        label=doc,
                        claim_id="c1",
                        citations=[await self._citation(facts[fid].support_chunk_ids[0])],
                        strength=0.5,
                    )
                    for doc, fid in zip(case.document_ids, case.fact_ids, strict=True)
                ]
                contradictions.append(
                    Contradiction(id="k1", subject=case.subject, sides=sides, stronger_side=0)
                )
        return Answer(summary="ok", claims=claims, contradictions=contradictions, **base)

    async def kpis(
        self, deal_id: str, *, access: AccessContext, periods: Sequence[str] | None = None
    ) -> list[KpiValue]:
        return [
            KpiValue(
                kpi_id=row.kpi_id,
                period=row.period,
                value=row.value,
                unit=row.unit,
                status="computed",
                formula_inputs={"x": 1.0},
            )
            for row in self._truth.kpi_truth
        ]

    async def screen(self, request: ScreeningRequest, *, access: AccessContext) -> ScreeningResult:
        return await super().screen(request, access=access)

    async def judge(self, claim: str, passage: str, quote: str | None = None) -> JudgeVerdict:
        for label in self._truth.judge_labels:
            chunk = await self._store.get_chunk(label.chunk_id, self._truth.access())
            if label.claim == claim and chunk is not None and chunk.text == passage:
                return JudgeVerdict(label=label.label, checks_passed=True)
        raise AssertionError("unknown claim")


async def test_oracle_scores_perfectly(smoke_store: Store) -> None:
    truth = smoke_truth()
    result = await evaluate_seed(
        "oracle", store=smoke_store, truth=truth, adapter=OracleAdapter(smoke_store, truth)
    )
    summary = summarise(
        [result], provider="mock", sweep_notes={}, hand_labels=None, n_resamples=200
    )
    for system in SYSTEMS:
        assert summary["retrieval"]["systems"][system]["ndcg@10"]["estimate"] == pytest.approx(1.0)
        assert summary["retrieval"]["systems"][system]["mrr"]["estimate"] == pytest.approx(1.0)
    citation = summary["citation"]["metrics"]
    assert citation["citation_precision"]["verifier_on"]["estimate"] == pytest.approx(1.0)
    assert citation["citation_recall"]["verifier_on"]["estimate"] == pytest.approx(1.0)
    assert citation["unsupported_claim_rate"]["verifier_on"]["estimate"] == pytest.approx(0.0)
    assert summary["abstention"]["end_to_end"]["correct_abstention"]["estimate"] == pytest.approx(
        1.0
    )
    assert summary["abstention"]["end_to_end"]["false_abstention"]["estimate"] == pytest.approx(0.0)
    contradiction = summary["contradiction"]
    assert contradiction["recall"]["estimate"] == pytest.approx(1.0)
    assert contradiction["false_positive_rate"]["estimate"] == pytest.approx(0.0)
    assert contradiction["completeness"]["both_sides_cited"] == pytest.approx(1.0)
    assert contradiction["stronger_side_agreement"]["share"] == pytest.approx(1.0)
    assert contradiction["superseded_withdrawn"]["flagged"] == 1
    assert summary["kpi"]["accuracy"]["estimate"] == pytest.approx(1.0)
    assert summary["judge"]["kappa"]["estimate"] == pytest.approx(1.0)
    assert summary["verifier"]["metrics"]["recall_not_supported"]["estimate"] == pytest.approx(1.0)


async def test_stub_run_has_the_expected_units(smoke_store: Store) -> None:
    truth = smoke_truth()
    adapter = Adapter(store=smoke_store, llm=build_mock_llm(), buyers=truth.buyers, use_real=False)
    result = await evaluate_seed("smoke", store=smoke_store, truth=truth, adapter=adapter)
    tests = [q.id for q in truth.queries if split_of(q.id) == "test"]
    assert result.query_ids == tests
    facts = truth.facts_by_id()
    queries = truth.queries_by_id()
    assert result.clusters == [facts[queries[q].gold_fact_ids[0]].document_id for q in tests]
    assert set(result.retrieval) == {"ndcg@10", "recall@5", "recall@10", "recall@30", "mrr"}
    assert all(len(v) == len(tests) for v in result.retrieval["mrr"].values())
    assert result.abstention is not None
    assert result.abstention.tau != float("-inf")
    # tau is chosen on dev only: the dev answerable queries are exactly the dev split.
    assert len(result.abstention.dev_answerable) == len(truth.queries) - len(tests)
    assert len(result.abstention.test_unanswerable) == len(result.abstention.test_unanswerable_hard)
    assert len(result.citation["on"].n_claims) == len(tests)
    assert len(result.verifier.truth) == 7  # the test split of the constructed labels
    assert len(result.kpi) == 4 and all(c.outcome.value is None for c in result.kpi)
    assert {p for _, p in result.screening} == {"unknown"}
    assert result.contradiction.planted == [False]  # a stub never reports a contradiction
    assert result.contradiction.controls == [False]


async def test_tau_does_not_depend_on_test_queries(smoke_store: Store) -> None:
    truth = smoke_truth()
    adapter = Adapter(store=smoke_store, llm=build_mock_llm(), buyers=truth.buyers, use_real=False)
    base = await evaluate_seed("a", store=smoke_store, truth=truth, adapter=adapter)
    changed = TruthBundle(
        **{
            **truth.__dict__,
            "unanswerable": [u for u in truth.unanswerable if split_of(u.id) == "dev"],
        }
    )
    other = await evaluate_seed("b", store=smoke_store, truth=changed, adapter=adapter)
    assert base.abstention is not None and other.abstention is not None
    assert base.abstention.tau == other.abstention.tau


async def test_all_queries_use_test_split_only(smoke_store: Store) -> None:
    truth = smoke_truth()
    adapter = Adapter(store=smoke_store, llm=build_mock_llm(), buyers=truth.buyers, use_real=False)
    result = await evaluate_seed("smoke", store=smoke_store, truth=truth, adapter=adapter)
    assert all(split_of(qid) == "test" for qid in result.query_ids)
