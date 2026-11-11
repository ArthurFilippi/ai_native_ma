"""The access predicate lives inside the store query: zero leakage across users."""

from __future__ import annotations

import random

import pytest

from ainma.contracts import AccessContext, BuyerProfile, BuyerType, DocType
from ainma.store import Store, UnknownUserError
from tests.fixtures.tiny import chunk_document, tiny_documents


def _deal_of_chunk() -> dict[str, str | None]:
    return {c.id: c.deal_id for d in tiny_documents() for c in chunk_document(d)}


async def test_outsider_sees_only_the_general_layer(any_store: Store) -> None:
    access = await any_store.access_for("u_outsider")
    chunks = await any_store.candidates(access, deal_id="deal_aurora")
    assert chunks, "the general layer must stay visible"
    assert {c.deal_id for c in chunks} == {None}


async def test_analyst_sees_aurora_but_not_borealis(any_store: Store) -> None:
    access = await any_store.access_for("u_analyst")
    aurora = await any_store.candidates(access, deal_id="deal_aurora")
    assert {c.deal_id for c in aurora} == {"deal_aurora", None}
    borealis = await any_store.candidates(access, deal_id="deal_borealis")
    assert "deal_borealis" not in {c.deal_id for c in borealis}


async def test_direct_access_by_id_is_filtered(any_store: Store) -> None:
    outsider = await any_store.access_for("u_outsider")
    assert await any_store.get_chunk("doc_cim_p2_00", outsider) is None
    assert await any_store.get_page("doc_cim", 2, outsider) is None
    assert await any_store.get_document("doc_cim", outsider) is None
    assert await any_store.get_deal("deal_aurora", outsider) is None
    assert await any_store.list_deals(outsider) == []
    analyst = await any_store.access_for("u_analyst")
    assert await any_store.get_chunk("doc_cim_p2_00", analyst) is not None
    assert await any_store.get_page("doc_cim", 2, analyst) is not None


async def test_no_general_layer_means_no_general_chunks(any_store: Store) -> None:
    access = AccessContext(user_id="x", allowed_deal_ids=frozenset(), include_general_layer=False)
    assert await any_store.candidates(access, deal_id=None) == []
    assert await any_store.list_documents(access, None) == []


async def test_property_zero_leakage_over_random_users(any_store: Store) -> None:
    rng = random.Random(1234)
    deal_of = _deal_of_chunk()
    deals = ["deal_aurora", "deal_borealis", "deal_unknown"]
    types = list(DocType)
    for _ in range(200):
        allowed = frozenset(d for d in deals if rng.random() < 0.5)
        general = rng.random() < 0.7
        access = AccessContext(
            user_id="rand", allowed_deal_ids=allowed, include_general_layer=general
        )
        scope = rng.choice([None, *deals])
        doc_types = rng.choice([None, rng.sample(types, k=rng.randint(0, 3))])
        got = await any_store.candidates(access, deal_id=scope, doc_types=doc_types)
        for chunk in got:
            deal = deal_of[chunk.id]
            assert deal in allowed or (deal is None and general), f"leak of {chunk.id}"
            assert deal is None or deal == scope
            if doc_types is not None:
                assert chunk.doc_type in doc_types
        for doc in await any_store.list_documents(access, scope):
            assert doc.deal_id in allowed or (doc.deal_id is None and general)


async def test_unknown_user_is_distinct_from_no_membership(any_store: Store) -> None:
    with pytest.raises(UnknownUserError):
        await any_store.access_for("u_ghost")
    outsider = await any_store.access_for("u_outsider")
    assert outsider.allowed_deal_ids == frozenset()


async def test_chunks_must_be_exact_page_slices(any_store: Store) -> None:
    chunk = chunk_document(tiny_documents()[0])[0]
    bad = chunk.model_copy(update={"id": "bad", "text": "not the page text"})
    with pytest.raises(ValueError, match="page slice"):
        await any_store.put_chunks([bad])


async def test_buyer_universe_roundtrip(any_store: Store) -> None:
    buyer = BuyerProfile(
        id="b_x",
        name="Fictional Partners I",
        buyer_type=BuyerType.FINANCIAL,
        sectors=["industrial components"],
        geographies=["DACH"],
        size_eur_m=500.0,
    )
    await any_store.put_buyer(buyer)
    assert await any_store.list_buyers() == [buyer]


async def test_the_pipeline_answers_from_either_backend(any_store: Store) -> None:
    """The same question gives the same cited answer on SQLite and on Postgres (D101)."""
    from ainma.llm import build_mock_llm
    from ainma.pipeline import PipelineConfig, ask

    access = await any_store.access_for("u_analyst")
    answer = await ask(
        "What was FY2024 revenue?",
        store=any_store,
        access=access,
        deal_id="deal_aurora",
        llm=build_mock_llm(),
        config=PipelineConfig(answers_log=None),
    )
    assert not answer.abstained and answer.contradictions
    citation = answer.claims[0].citations[0]
    page = await any_store.get_page(citation.document_id, citation.page, access)
    assert page is not None and page[citation.char_start : citation.char_end] == citation.quote
