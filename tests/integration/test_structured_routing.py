"""A keyed question is answered from the structured base with a verifiable provenance, and its
disagreeing documents become a contradiction (D92)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from ainma.contracts import AccessContext, ClaimStatus
from ainma.factbase import FactBase
from ainma.ingest.loader import load_corpus
from ainma.llm import build_mock_llm
from ainma.pipeline import PipelineConfig, ask
from ainma.store import SqliteStore

SEED_DIR = Path("data/synthetic/1234")
pytestmark = pytest.mark.skipif(
    not (SEED_DIR / "structured" / "factbase.json").exists(), reason="run `make data` first"
)
CONFIG = PipelineConfig(answers_log=None)


@pytest.fixture
async def corpus() -> AsyncIterator[tuple[SqliteStore, FactBase]]:
    store = await SqliteStore.open(":memory:")
    await load_corpus(store, SEED_DIR)
    base = FactBase.load(SEED_DIR)
    assert base is not None
    yield store, base
    await store.close()


async def test_keyed_question_is_answered_from_the_structured_base(
    corpus: tuple[SqliteStore, FactBase],
) -> None:
    store, base = corpus
    access = await store.access_for("u_analyst")
    answer = await ask(
        "What was Aurora Components revenue in FY2024?",
        store=store,
        access=access,
        deal_id="deal_aurora",
        llm=build_mock_llm(),
        config=CONFIG,
        factbase=base,
    )
    structured = [c for c in answer.claims if c.origin == "structured"]
    assert structured and not answer.abstained
    first = structured[0]
    assert "182.4" in first.text and first.status is ClaimStatus.SOURCED
    assert first.verification is not None and first.verification.supported
    page = await store.get_page(first.citations[0].document_id, first.citations[0].page, access)
    assert page is not None
    citation = first.citations[0]
    assert page[citation.char_start : citation.char_end] == citation.quote
    # the trade press figure is shown as the other side, no winner picked
    assert any("179" in c.text for c in structured)
    assert answer.contradictions


async def test_routing_off_and_no_access_fall_back_to_text(
    corpus: tuple[SqliteStore, FactBase],
) -> None:
    store, base = corpus
    access = await store.access_for("u_analyst")
    question = "What was Aurora Components revenue in FY2024?"
    text_only = await ask(
        question,
        store=store,
        access=access,
        deal_id="deal_aurora",
        llm=build_mock_llm(),
        config=CONFIG.model_copy(update={"structured_routing": False}),
        factbase=base,
    )
    assert all(c.origin == "text" for c in text_only.claims)
    outsider = AccessContext(user_id="u_outsider", allowed_deal_ids=frozenset())
    answer = await ask(
        question,
        store=store,
        access=outsider,
        deal_id=None,
        llm=build_mock_llm(),
        config=CONFIG,
        factbase=base,
    )
    assert all(c.origin == "text" for c in answer.claims)


async def test_growth_questions_stay_on_the_text_path(
    corpus: tuple[SqliteStore, FactBase],
) -> None:
    store, base = corpus
    access = await store.access_for("u_analyst")
    answer = await ask(
        "How did Aurora Components revenue grow in FY2024?",
        store=store,
        access=access,
        deal_id="deal_aurora",
        llm=build_mock_llm(),
        config=CONFIG,
        factbase=base,
    )
    assert all(c.origin == "text" for c in answer.claims)


async def test_a_superseded_draft_is_still_shown_and_flagged(
    corpus: tuple[SqliteStore, FactBase],
) -> None:
    """Regression: a routed answer cited only the current document and lost the superseded
    draft (the text path shows it flagged), which the harness counted as cited without the flag."""
    from ainma.contracts import Flag

    store, base = corpus
    access = await store.access_for("u_analyst")
    answer = await ask(
        "What is the enterprise value of Aurora Components in the SPA?",
        store=store,
        access=access,
        deal_id="deal_aurora",
        llm=build_mock_llm(),
        config=CONFIG,
        factbase=base,
    )
    structured = [c for c in answer.claims if c.origin == "structured"]
    assert structured
    assert any(Flag.SUPERSEDED in c.flags for c in structured)
