"""Search on the tiny corpus: systems A1 to A5, access control, caching, withdrawn handling."""

from __future__ import annotations

import random

import pytest

from ainma.contracts import AccessContext
from ainma.retrieval import RetrievalConfig, RetrievalEngine, search, search_detailed
from ainma.store import SqliteStore

QUERY = "What was FY2024 revenue?"
COMPONENTS = {"bm25", "dense", "rrf", "rerank", "tier_weight", "recency", "corroboration"}


async def _access(store: SqliteStore, user: str) -> AccessContext:
    return await store.access_for(user)


@pytest.mark.parametrize("system", ["A1", "A2", "A3", "A4", "A5"])
async def test_every_system_finds_the_cim_revenue_passage(
    tiny_store: SqliteStore, system: str
) -> None:
    access = await _access(tiny_store, "u_analyst")
    config = RetrievalConfig(system=system)  # type: ignore[arg-type]
    hits = await search(
        QUERY, store=tiny_store, access=access, deal_id="deal_aurora", config=config
    )
    assert hits, system
    ranked = [h.chunk.id for h in hits]
    # the keyword and dense systems can be fooled by "17 percent of FY2024 revenue"; the
    # reranker, which checks that the passage states revenue as a number, is not
    assert "doc_cim_p2_00" in ranked[:3], system
    if system == "A4":  # status blind: the withdrawn press release is an exact match too
        assert ranked[:2] == ["doc_pr_orig_p1_01", "doc_cim_p2_00"]
    if system == "A5":
        assert ranked[0] == "doc_cim_p2_00"
    assert [h.passage.rank for h in hits] == list(range(1, len(hits) + 1))
    assert set(hits[0].passage.components) >= COMPONENTS
    assert hits[0].passage.explanation.endswith(".")
    assert 0.0 <= hits[0].passage.final_score <= 1.0
    assert hits[0].document.id == hits[0].chunk.document_id


async def test_a5_applies_tier_recency_and_never_returns_withdrawn(
    tiny_store: SqliteStore,
) -> None:
    access = await _access(tiny_store, "u_analyst")
    result = await search_detailed(QUERY, store=tiny_store, access=access, deal_id="deal_aurora")
    ids = [h.chunk.document_id for h in result.hits]
    assert "doc_pr_orig" not in ids
    assert [h.chunk.document_id for h in result.withdrawn] == ["doc_pr_orig"]
    assert result.withdrawn[0].passage.final_score == 0.0
    cim = next(h for h in result.hits if h.chunk.id == "doc_cim_p2_00")
    news = next(h for h in result.hits if h.chunk.document_id == "doc_news_17")
    assert cim.passage.components["tier_weight"] == 0.8
    assert news.passage.components["tier_weight"] == 0.45
    assert cim.passage.components["recency"] == pytest.approx(1.0)  # newest document: as_of
    assert news.passage.components["recency"] == pytest.approx(0.5 ** (40 / 120))
    assert cim.passage.final_score > news.passage.final_score
    # A3 is status blind: the withdrawn press release is an ordinary hit
    a3 = await search(
        QUERY,
        store=tiny_store,
        access=access,
        deal_id="deal_aurora",
        config=RetrievalConfig(system="A3"),
    )
    assert "doc_pr_orig" in [h.chunk.document_id for h in a3]


async def test_corroboration_bonus_needs_independent_agreeing_documents(
    tiny_store: SqliteStore,
) -> None:
    access = await _access(tiny_store, "u_analyst")
    hits = await search(QUERY, store=tiny_store, access=access, deal_id="deal_aurora")
    # CIM says 182.4, press says 179: nobody agrees, so no bonus anywhere
    assert all(h.passage.components["corroboration"] == 0.0 for h in hits)


async def test_outsider_retrieves_zero_chunks_of_a_deal(tiny_store: SqliteStore) -> None:
    outsider = await _access(tiny_store, "u_outsider")
    hits = await search(QUERY, store=tiny_store, access=outsider, deal_id="deal_aurora")
    assert hits == []
    for system in ("A1", "A2", "A3", "A4", "A5"):
        generous = RetrievalConfig(system=system, top_k=50)  # type: ignore[arg-type]
        found = await search(
            "revenue Aurora Borealis net FY2024 EUR million",
            store=tiny_store,
            access=outsider,
            deal_id="deal_aurora",
            config=generous,
        )
        assert all(h.chunk.deal_id is None for h in found)


async def test_no_leakage_for_random_users_and_queries(tiny_store: SqliteStore) -> None:
    rng = random.Random(7)
    vocabulary = [
        "revenue", "margin", "aurora", "borealis", "codename", "playbook", "bidder", "FY2024",
        "customer", "press", "sell-side", "information", "memorandum", "EUR", "million",
    ]  # fmt: skip
    engine = RetrievalEngine()
    for _ in range(40):
        user = rng.choice(["u_lead", "u_analyst", "u_outsider"])
        deal = rng.choice(["deal_aurora", "deal_borealis", None])
        query = " ".join(rng.choices(vocabulary, k=rng.randint(1, 4)))
        access = await _access(tiny_store, user)
        hits = await search(
            query,
            store=tiny_store,
            access=access,
            deal_id=deal,
            config=RetrievalConfig(top_k=50),
            engine=engine,
        )
        for hit in hits:
            assert hit.chunk.deal_id is None or hit.chunk.deal_id in access.allowed_deal_ids
            assert hit.chunk.deal_id in (None, deal)


async def test_fitted_indexes_are_cached_by_candidate_set(tiny_store: SqliteStore) -> None:
    engine = RetrievalEngine()
    analyst = await _access(tiny_store, "u_analyst")
    lead = await _access(tiny_store, "u_lead")
    for query in (QUERY, "gross margin", "largest customer"):
        await search(query, store=tiny_store, access=analyst, deal_id="deal_aurora", engine=engine)
    assert engine.fits == 1
    await search(QUERY, store=tiny_store, access=lead, deal_id="deal_borealis", engine=engine)
    assert engine.fits == 2  # another candidate set
    await search(QUERY, store=tiny_store, access=analyst, deal_id="deal_aurora", engine=engine)
    assert engine.fits == 2


async def test_search_is_deterministic(tiny_store: SqliteStore) -> None:
    access = await _access(tiny_store, "u_analyst")
    first = await search(QUERY, store=tiny_store, access=access, deal_id="deal_aurora")
    second = await search(QUERY, store=tiny_store, access=access, deal_id="deal_aurora")
    assert [h.model_dump() for h in first] == [h.model_dump() for h in second]


async def test_general_layer_question_without_a_deal(tiny_store: SqliteStore) -> None:
    access = await _access(tiny_store, "u_analyst")
    hits = await search(
        "bidder communication channel", store=tiny_store, access=access, deal_id=None
    )
    assert hits and all(h.chunk.deal_id is None for h in hits)
    assert hits[0].chunk.document_id == "doc_playbook"
