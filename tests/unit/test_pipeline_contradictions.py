from __future__ import annotations

from datetime import date

import pytest

from ainma.contracts import Answer, ClaimStatus, DocStatus, DocType, Flag
from ainma.llm import build_mock_llm
from ainma.pipeline import PipelineConfig, ask
from ainma.store import SqliteStore
from tests.fixtures_core.scripted import add_doc

CONFIG = PipelineConfig(answers_log=None)
QUESTION = "What was FY2024 revenue?"


async def _ask(store: SqliteStore, question: str = QUESTION) -> Answer:
    access = await store.access_for("u_analyst")
    return await ask(
        question,
        store=store,
        access=access,
        deal_id="deal_aurora",
        llm=build_mock_llm(),
        config=CONFIG,
    )


async def test_cim_against_trade_press_is_a_contradiction(tiny_store: SqliteStore) -> None:
    answer = await _ask(tiny_store)
    assert len(answer.contradictions) == 1
    k = answer.contradictions[0]
    assert k.subject == "Project Aurora FY2024 revenue"
    assert {s.label for s in k.sides} == {"EUR 182.4 million", "EUR 179 million"}
    docs = {s.citations[0].document_id for s in k.sides}
    assert docs == {"doc_cim", "doc_news_17"}
    assert all(s.citations and s.citations[0].quote for s in k.sides)
    # tier weight x recency: CIM 0.8 x 1.0, press 0.45 x 0.5 ** (40 / 120)
    strengths = {s.citations[0].document_id: s.strength for s in k.sides}
    assert strengths["doc_cim"] == pytest.approx(0.8)
    assert strengths["doc_news_17"] == pytest.approx(0.45 * 0.5 ** (40 / 120))
    assert k.stronger_side == 0 and k.sides[0].citations[0].document_id == "doc_cim"
    assert "does not pick a winner" in k.note
    claims = {c.id: c for c in answer.claims}
    for side in k.sides:
        assert Flag.CONTRADICTED in claims[side.claim_id].flags
    assert "Sources disagree" in answer.summary


async def test_consistent_control_is_not_a_contradiction(tiny_store: SqliteStore) -> None:
    # same fact restated by an independent document: corroboration, not conflict
    await add_doc(
        tiny_store,
        "doc_press_ok",
        "Aurora reported net revenue for FY2024 of EUR 182.4 million.",
        doc_type=DocType.PRESS_RELEASE,
    )
    answer = await _ask(tiny_store)
    docs = {c.document_id for claim in answer.claims for c in claim.citations}
    assert {"doc_cim", "doc_press_ok"} <= docs
    keys = [k.subject for k in answer.contradictions]
    # the only disagreement left is the trade press article, and it now has two sides:
    # the two agreeing documents form ONE side
    assert len(answer.contradictions) == 1 and len(answer.contradictions[0].sides) == 2
    agreeing = next(s for s in answer.contradictions[0].sides if s.label == "EUR 182.4 million")
    assert {c.document_id for c in agreeing.citations} == {"doc_cim", "doc_press_ok"}
    assert keys == ["Project Aurora FY2024 revenue"]


async def test_no_contradiction_when_every_source_agrees(tiny_store: SqliteStore) -> None:
    answer = await _ask(tiny_store, "What was the gross margin in FY2024?")
    assert answer.contradictions == []
    assert not answer.abstained


async def test_documents_with_identical_content_are_not_independent(
    tiny_store: SqliteStore,
) -> None:
    question = "What was EBITDA in FY2024?"
    await add_doc(tiny_store, "doc_a", "EBITDA for FY2024 was EUR 30.0 million.", sha="same-bytes")
    await add_doc(tiny_store, "doc_b", "EBITDA for FY2024 was EUR 33.0 million.", sha="same-bytes")
    answer = await _ask(tiny_store, question)
    assert {c.citations[0].document_id for c in answer.claims if c.citations} == {"doc_a", "doc_b"}
    assert answer.contradictions == []
    # an independent third document that disagrees with one of them does contradict
    await add_doc(tiny_store, "doc_c", "EBITDA for FY2024 was EUR 33.0 million.", sha="other")
    answer = await _ask(tiny_store, question)
    assert len(answer.contradictions) == 1
    assert {s.label for s in answer.contradictions[0].sides} == {
        "EUR 30.0 million",
        "EUR 33.0 million",
    }


async def test_superseded_document_is_flagged_not_contradicted(tiny_store: SqliteStore) -> None:
    await add_doc(
        tiny_store,
        "doc_cim_draft",
        "Net revenue for FY2024 was forecast at EUR 175.0 million.",
        doc_type=DocType.DEAL_DOCUMENT,
        status=DocStatus.SUPERSEDED,
        superseded_by="doc_cim",
        published_on=date(2025, 1, 10),
    )
    answer = await _ask(tiny_store)
    superseded = [
        c
        for c in answer.claims
        if c.status is ClaimStatus.SOURCED and c.citations[0].document_id == "doc_cim_draft"
    ]
    assert superseded and all(Flag.SUPERSEDED in c.flags for c in superseded)
    for k in answer.contradictions:
        assert all(c.document_id != "doc_cim_draft" for s in k.sides for c in s.citations)
