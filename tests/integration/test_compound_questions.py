"""Compound questions on seed 1234: every half is answered with sources or shown as missing."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainma.contracts import Answer, ClaimStatus
from ainma.ingest.loader import load_corpus
from ainma.llm import build_mock_llm
from ainma.pipeline import PipelineConfig, ask
from ainma.store import SqliteStore
from ainma.synth.generate import generate


@pytest.fixture(scope="module")
def seed_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate(1234, tmp_path_factory.mktemp("synthetic"))


async def _ask(seed_dir: Path, question: str) -> Answer:
    store = await SqliteStore.open(":memory:")
    try:
        await load_corpus(store, seed_dir)
        access = await store.access_for("u_analyst")
        return await ask(
            question,
            store=store,
            access=access,
            deal_id="deal_aurora",
            llm=build_mock_llm(),
            config=PipelineConfig(answers_log=None),
        )
    finally:
        await store.close()


async def test_the_demo_sentence_answers_both_halves_with_citations(seed_dir: Path) -> None:
    answer = await _ask(
        seed_dir, "What was Aurora's gross margin and how concentrated is its customer base?"
    )
    assert len(answer.sub_questions) == 2
    sourced = [c for c in answer.claims if c.status is ClaimStatus.SOURCED]
    texts = " ".join(c.text for c in sourced)
    assert "gross margin" in texts and "largest customer share" in texts
    assert all(c.citations for c in sourced)
    assert not answer.abstained and not answer.missing


async def test_the_unanswerable_half_is_shown_as_missing_not_hidden(seed_dir: Path) -> None:
    answer = await _ask(
        seed_dir, "What was Aurora's gross margin and what is the CEO's compensation?"
    )
    assert not answer.abstained
    sourced = [c for c in answer.claims if c.status is ClaimStatus.SOURCED]
    assert len(sourced) == 1 and "gross margin" in sourced[0].text
    assert [m.topic for m in answer.missing] == ["CEO's compensation (Aurora)"]
    assert any(c.status is ClaimStatus.MISSING for c in answer.claims)
    assert len(answer.sub_questions) == 2
