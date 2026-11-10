"""The adapter returns the expected shapes from stubs, and talks to real modules by name."""

from __future__ import annotations

import json
import sys
import types
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from pydantic import BaseModel

from ainma.contracts import AccessContext, Answer, ClaimStatus, ScreeningRequest
from ainma.evaluation import adapter as adapter_module
from ainma.evaluation.adapter import Adapter, AdapterError, RankedChunk
from ainma.evaluation.resolve import resolve
from ainma.evaluation.smoke import load_smoke_store, smoke_truth
from ainma.llm import build_mock_llm


@pytest.fixture
async def stub_adapter() -> AsyncIterator[Adapter]:
    store = await load_smoke_store()
    yield Adapter(store=store, llm=build_mock_llm(), buyers=smoke_truth().buyers, use_real=False)
    await store.close()


ACCESS = smoke_truth().access()


async def test_modes_say_stub_when_real_modules_are_not_used(stub_adapter: Adapter) -> None:
    assert set(stub_adapter.modes.values()) == {"stub"}
    assert set(stub_adapter.modes) == {"search", "ask", "screening", "kpi", "judge", "checks"}


async def test_missing_targets_fall_back_to_stubs() -> None:
    # In a branch where the real modules are not merged, the guarded imports find nothing.
    store = await load_smoke_store()
    adapter = Adapter(store=store, llm=build_mock_llm())
    assert resolve("ainma.nonexistent_module", "anything") is None
    assert all(mode in {"real", "stub"} for mode in adapter.modes.values())
    await store.close()


@pytest.mark.parametrize("system", ["A1", "A2", "A3", "A4", "A5"])
async def test_search_returns_ranked_chunks_for_every_system(
    stub_adapter: Adapter, system: str
) -> None:
    hits = await stub_adapter.search(
        "What was Aurora net revenue for FY2024?",
        access=ACCESS,
        deal_id="deal_aurora",
        system=system,
        top_k=5,
    )
    assert 0 < len(hits) <= 5
    assert all(isinstance(h, RankedChunk) for h in hits)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    assert "doc_cim_p2_00" in [h.chunk_id for h in hits]
    if system == "A5":
        # the source ranker excludes the withdrawn press release that BM25 likes
        assert hits[0].chunk_id == "doc_cim_p2_00"
        assert "doc_pr_orig_p1_01" not in [h.chunk_id for h in hits]


async def test_search_respects_the_access_filter(stub_adapter: Adapter) -> None:
    nobody = AccessContext(user_id="x", allowed_deal_ids=frozenset(), include_general_layer=False)
    hits = await stub_adapter.search(
        "Aurora revenue", access=nobody, deal_id="deal_aurora", system="A1"
    )
    assert hits == []


async def test_stub_ask_cites_a_verbatim_quote_and_abstains_below_tau(
    stub_adapter: Adapter,
) -> None:
    answer = await stub_adapter.ask(
        "What was Aurora net revenue for FY2024?", access=ACCESS, deal_id="deal_aurora"
    )
    assert isinstance(answer, Answer)
    assert not answer.abstained
    first = answer.claims[0]
    assert first.status is ClaimStatus.SOURCED
    chunk_text = "Net revenue for FY2024 reached EUR 182.4 million (FY2023: EUR 168.0 million)."
    assert first.citations[0].quote == chunk_text
    assert answer.trace.provider == "stub"

    abstained = await stub_adapter.ask(
        "What was Aurora net revenue for FY2024?", access=ACCESS, deal_id="deal_aurora", tau=99.0
    )
    assert abstained.abstained
    assert all(c.status is ClaimStatus.MISSING for c in abstained.claims)


async def test_stub_ask_without_overlap_abstains(stub_adapter: Adapter) -> None:
    answer = await stub_adapter.ask("zzz qqq", access=ACCESS, deal_id="deal_aurora")
    assert answer.abstained


async def test_stub_screening_never_guesses(stub_adapter: Adapter) -> None:
    result = await stub_adapter.screen(ScreeningRequest(deal_id="deal_aurora"), access=ACCESS)
    assert len(result.cards) == 2
    assert {r.status.value for c in result.cards for r in c.results} == {"unknown"}


async def test_stub_kpis_extract_nothing(stub_adapter: Adapter) -> None:
    assert await stub_adapter.kpis("deal_aurora", access=ACCESS) == []


async def test_stub_judge_labels_and_checks(stub_adapter: Adapter) -> None:
    passage = "Net revenue for FY2024 reached EUR 182.4 million (FY2023: EUR 168.0 million)."
    supported = await stub_adapter.judge(
        "Net revenue for FY2024 reached EUR 182.4 million.", passage
    )
    assert supported.label == "supported"
    assert supported.checks_passed
    altered = await stub_adapter.judge("Net revenue for FY2024 reached EUR 190.4 million.", passage)
    assert altered.label != "supported"
    assert not altered.checks_passed
    unrelated = await stub_adapter.judge("Patents expire in 2031.", passage)
    assert unrelated.label == "unsupported"
    bad_quote = await stub_adapter.judge("Revenue was 182.4.", passage, quote="EUR 182.5 million")
    assert not bad_quote.checks_passed


async def test_stub_adapter_has_no_sweeps_to_run(stub_adapter: Adapter) -> None:
    sweeps = stub_adapter.sweeps()
    assert [s.name for s in sweeps] == ["tier prior uniform", "RRF weights", "recency half-life"]
    assert all(s.variants == () for s in sweeps)
    assert stub_adapter.backends() == {"dense": "stub", "reranker": "stub"}
    assert stub_adapter.config_snapshot() == {}


# ---------------------------------------------------------------------- real path by name


class FakeRanker(BaseModel):
    tier_weights: dict[int, float] = {1: 1.0, 2: 0.8}
    half_life_days: dict[str, float] = {"press_article": 120.0, "deal_document": 365.0}


class FakeRetrievalConfig(BaseModel):
    system: str = "A5"
    top_k: int = 10
    rrf_weights: tuple[float, float] = (1.0, 1.0)
    embedder: str = "lsa"
    reranker: str = "features"
    ranker: FakeRanker = FakeRanker()


class FakePipelineConfig(BaseModel):
    retrieval: FakeRetrievalConfig = FakeRetrievalConfig()
    verifier: bool = True
    tau: float = 0.1
    abstain_score: Literal["relevance", "final"] = "relevance"
    answers_log: Path | None = Path("data/cache/answers.jsonl")


class FakeJudgeRequest(BaseModel):
    claim: str
    quotes: list[str]
    context: str = ""


class FakeJudgeResult(BaseModel):
    label: Literal["supported", "partial", "unsupported"]
    rationale: str = ""


@pytest.fixture
def fake_modules(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    class FakeEngine:
        pass

    async def search(
        query: str, *, store: Any, access: Any, deal_id: Any, config: Any, engine: Any = None
    ) -> Any:
        seen["search_config"] = config
        seen["engine"] = engine
        passage = SimpleNamespace(final_score=0.5, components={"relevance": 0.9})
        return [SimpleNamespace(chunk=SimpleNamespace(id="c_real"), passage=passage)]

    async def ask(
        question: str, *, store: Any, access: Any, deal_id: Any, llm: Any, config: Any
    ) -> Any:
        seen["pipeline_config"] = config
        return await adapter_module.stubs.stub_ask(
            question, store=store, access=access, deal_id=deal_id, verifier=True, tau=None
        )

    module = types.ModuleType("fake_real")
    module.search = search  # type: ignore[attr-defined]
    module.RetrievalEngine = FakeEngine  # type: ignore[attr-defined]
    module.ask = ask  # type: ignore[attr-defined]
    module.RetrievalConfig = FakeRetrievalConfig  # type: ignore[attr-defined]
    module.PipelineConfig = FakePipelineConfig  # type: ignore[attr-defined]
    module.JudgeRequest = FakeJudgeRequest  # type: ignore[attr-defined]
    module.JudgeResult = FakeJudgeResult  # type: ignore[attr-defined]
    module.JUDGE = "judge system prompt"  # type: ignore[attr-defined]
    module.verbatim_span = lambda quote, text: quote in text  # type: ignore[attr-defined]
    module.numeric_match = lambda claim, quote: (True, "")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_real", module)
    wiring = {
        "search": "search",
        "ask": "ask",
        "judge_request": "JudgeRequest",
        "judge_result": "JudgeResult",
        "judge_prompt": "JUDGE",
        "retrieval_config": "RetrievalConfig",
        "retrieval_engine": "RetrievalEngine",
        "pipeline_config": "PipelineConfig",
        "verbatim_span": "verbatim_span",
        "numeric_match": "numeric_match",
    }
    for target, attribute in wiring.items():
        monkeypatch.setitem(adapter_module.TARGETS, target, (("fake_real", attribute),))
    return seen


class RecordingJudgeLLM:
    provider = "fake"
    model = "fake"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def complete_json(
        self, *, task: str, system: str, user: str, schema: Any, stage: str
    ) -> tuple[Any, Any]:
        self.calls.append({"task": task, "system": system, "user": user, "stage": stage})
        return schema(label="partial", rationale="r"), None


async def test_real_modules_are_called_by_name(fake_modules: dict[str, Any]) -> None:
    store = await load_smoke_store()
    llm = RecordingJudgeLLM()
    adapter = Adapter(store=store, llm=llm)  # type: ignore[arg-type]
    assert adapter.modes["search"] == "real"
    assert adapter.modes["ask"] == "real"
    assert adapter.modes["judge"] == "real"
    assert adapter.modes["checks"] == "real"
    assert adapter.modes["screening"] == "stub"
    assert adapter.backends() == {"dense": "lsa", "reranker": "features"}
    assert adapter.abstain_basis == "relevance"
    assert adapter.config_snapshot()["retrieval"]["system"] == "A5"

    hits = await adapter.search("q", access=ACCESS, deal_id=None, system="A3", top_k=7)
    # `support` is the relevance component because the pipeline thresholds on it
    assert hits == [RankedChunk("c_real", 0.5, 0.9)]
    assert fake_modules["search_config"].system == "A3"
    assert fake_modules["search_config"].top_k == 7
    first_engine = fake_modules["engine"]
    assert first_engine is not None  # one engine is passed so fitted indexes are reused
    await adapter.search("q2", access=ACCESS, deal_id=None, system="A1")
    assert fake_modules["engine"] is first_engine

    await adapter.ask(
        "What was Aurora net revenue for FY2024?",
        access=ACCESS,
        deal_id=None,
        verifier=False,
        tau=0.3,
    )
    config = fake_modules["pipeline_config"]
    assert config.verifier is False
    assert config.tau == 0.3
    assert config.retrieval.system == "A5"
    assert config.answers_log is None  # the evaluation does not write to the live answer log

    verdict = await adapter.judge("claim 1", "passage 1", quote="not in passage")
    assert verdict.label == "partial"
    assert not verdict.checks_passed  # the real verbatim check rejects the quote
    assert llm.calls[0]["task"] == "judge"
    assert llm.calls[0]["system"] == "judge system prompt"
    assert json.loads(llm.calls[0]["user"])["quotes"] == ["not in passage"]
    await store.close()


async def test_real_adapter_builds_sweeps_from_nested_config(
    fake_modules: dict[str, Any],
) -> None:
    store = await load_smoke_store()
    adapter = Adapter(store=store, llm=build_mock_llm())
    sweeps = {s.name: s for s in adapter.sweeps()}
    tier = sweeps["tier prior uniform"]
    assert tier.field == "ranker.tier_weights"
    assert dict(tier.variants)["uniform"]["ranker"].tier_weights == {1: 1.0, 2: 1.0}
    half = dict(sweeps["recency half-life"].variants)
    assert half["x0.5"]["ranker"].half_life_days == {"press_article": 60.0, "deal_document": 182.5}
    assert [label for label, _ in sweeps["RRF weights"].variants] == ["first x2", "second x2"]
    assert dict(sweeps["RRF weights"].variants)["second x2"] == {"rrf_weights": (1.0, 2.0)}
    # an override produced by a sweep is accepted by the search entry point
    _, overrides = tier.variants[0]
    await adapter.search("q", access=ACCESS, deal_id=None, system="A5", overrides=overrides)
    assert fake_modules["search_config"].ranker.tier_weights == {1: 1.0, 2: 1.0}
    with pytest.raises(AdapterError, match="no field"):
        await adapter.search("q", access=ACCESS, deal_id=None, system="A5", overrides={"nope": 1})
    await store.close()
