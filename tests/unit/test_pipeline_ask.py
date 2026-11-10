from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ainma.contracts import VALUE_CONTRACT, Answer, ClaimStatus, DocStatus, DocType, Flag
from ainma.llm import build_mock_llm
from ainma.pipeline import PipelineConfig, ask, ask_detailed
from ainma.pipeline.inspect import find_entry
from ainma.pipeline.schemas import WriteResult
from ainma.retrieval import RetrievalConfig, RetrievalEngine
from ainma.store import SqliteStore
from tests.fixtures.tiny import tiny_documents
from tests.fixtures_core.scripted import ScriptedWriter, add_doc, draft

CONFIG = PipelineConfig(answers_log=None)


async def _ask(
    store: SqliteStore,
    question: str,
    user: str = "u_analyst",
    deal: str | None = "deal_aurora",
    config: PipelineConfig = CONFIG,
) -> Answer:
    access = await store.access_for(user)
    return await ask(
        question, store=store, access=access, deal_id=deal, llm=build_mock_llm(), config=config
    )


async def test_every_citation_is_a_verbatim_span_of_the_stored_page(
    tiny_store: SqliteStore,
) -> None:
    answer = await _ask(tiny_store, "What was Aurora's FY2024 revenue and how did it grow?")
    access = await tiny_store.access_for("u_analyst")
    sourced = [c for c in answer.claims if c.status is ClaimStatus.SOURCED]
    assert sourced
    for claim in sourced:
        assert claim.verification is not None and claim.verification.supported
        for citation in claim.citations:
            page = await tiny_store.get_page(citation.document_id, citation.page, access)
            assert page is not None
            assert page[citation.char_start : citation.char_end] == citation.quote
    inferred = [c for c in answer.claims if c.status is ClaimStatus.INFERRED]
    assert len(inferred) == 1 and "8.6%" in inferred[0].text
    assert set(inferred[0].derived_from) <= {c.id for c in sourced}
    assert answer.sub_questions[1] == "FY2023 revenue Aurora"


async def test_answer_round_trips_through_the_contract(tiny_store: SqliteStore) -> None:
    answer = await _ask(tiny_store, "What was FY2024 revenue?")
    assert Answer.model_validate(answer.model_dump(mode="json")) == answer
    assert answer.value_contract == VALUE_CONTRACT
    assert answer.trace.provider == "mock" and answer.trace.model == "mock-extractive-v1"
    assert set(answer.trace.stage_latency_ms) >= {"understand", "retrieve", "write", "verify"}
    assert answer.trace.retrieved and answer.trace.retrieved[0].rank == 1


async def test_absent_topic_abstains_with_a_missing_claim(tiny_store: SqliteStore) -> None:
    answer = await _ask(tiny_store, "What is the CEO's compensation package?")
    assert answer.abstained
    assert answer.abstention_reason == "No retrieved passage scored above the support threshold."
    assert [c.status for c in answer.claims] == [ClaimStatus.MISSING]
    assert answer.missing[0].reason == "not_found"
    assert answer.value_contract == VALUE_CONTRACT
    assert "No claim is made" in answer.summary


async def test_outsider_gets_no_chunks_and_an_abstention(tiny_store: SqliteStore) -> None:
    answer = await _ask(tiny_store, "What was FY2024 revenue?", user="u_outsider")
    assert answer.abstained and answer.trace.retrieved == []
    assert all(c.status is ClaimStatus.MISSING for c in answer.claims)
    assert answer.value_contract == VALUE_CONTRACT


async def test_borealis_never_leaks_to_the_aurora_analyst(tiny_store: SqliteStore) -> None:
    answer = await _ask(tiny_store, "What was Borealis net revenue for FY2024?")
    assert all(c.document_id != "doc_other_cim" for claim in answer.claims for c in claim.citations)
    assert all("Borealis" not in claim.text for claim in answer.claims)


async def test_withdrawn_document_never_supports_a_claim(tiny_store: SqliteStore) -> None:
    answer = await _ask(tiny_store, "What was FY2024 revenue?")
    cited = {c.document_id for claim in answer.claims for c in claim.citations}
    assert "doc_pr_orig" not in cited
    assert all("190.0" not in claim.text for claim in answer.claims)
    flagged = [c for c in answer.claims if Flag.WITHDRAWN in c.flags]
    assert flagged  # the excluded retraction is surfaced, never cited
    # also with a status blind retrieval system the writer never sees the withdrawn passage
    a3 = await _ask(
        tiny_store,
        "What was FY2024 revenue?",
        config=PipelineConfig(answers_log=None, retrieval=RetrievalConfig(system="A3")),
    )
    assert "doc_pr_orig" not in {c.document_id for cl in a3.claims for c in cl.citations}


async def test_only_withdrawn_evidence_is_reported_as_withdrawn_only() -> None:
    store = await SqliteStore.open(":memory:")
    try:
        from tests.fixtures.tiny import tiny_deals, tiny_memberships, tiny_users

        for user in tiny_users():
            await store.put_user(user)
        for deal in tiny_deals():
            await store.put_deal(deal)
        for membership in tiny_memberships():
            await store.put_membership(membership)
        withdrawn = next(d for d in tiny_documents() if d.meta.id == "doc_pr_orig")
        await store.put_document(withdrawn.meta, withdrawn.pages)
        from tests.fixtures.tiny import chunk_document

        await store.put_chunks(chunk_document(withdrawn))
        answer = await _ask(store, "What was FY2024 revenue?")
    finally:
        await store.close()
    assert answer.abstained
    assert answer.missing[0].reason == "withdrawn_only"
    assert Flag.WITHDRAWN in answer.claims[0].flags
    assert all(not claim.citations for claim in answer.claims)
    assert (
        answer.abstention_reason
        == "The only relevant source is a withdrawn document, which is excluded."
    )


async def test_stale_claims_are_kept_and_flagged_never_hidden(tiny_store: SqliteStore) -> None:
    await add_doc(
        tiny_store,
        "doc_old_news",
        "Aurora announced a headcount of 1,250 employees at the end of 2021.",
        published_on=date(2022, 1, 5),
    )
    answer = await _ask(tiny_store, "What is Aurora's headcount?")
    assert not answer.abstained
    claim = next(c for c in answer.claims if c.status is ClaimStatus.SOURCED)
    assert Flag.STALE in claim.flags and Flag.SINGLE_LOW_TIER_SOURCE in claim.flags
    assert "old" in answer.summary


async def test_verifier_ablation_changes_what_survives(tiny_store: SqliteStore) -> None:
    doctored = ScriptedWriter(
        lambda: WriteResult(
            claims=[
                draft(
                    "d1",
                    "Net revenue for FY2024 reached EUR 190.0 million.",
                    1,
                    "Net revenue for FY2024 reached EUR 182.4 million",
                )
            ]
        )
    )
    access = await tiny_store.access_for("u_analyst")

    async def run(config: PipelineConfig) -> Answer:
        return (
            await ask_detailed(
                "What was FY2024 revenue?",
                store=tiny_store,
                access=access,
                deal_id="deal_aurora",
                llm=doctored,
                config=config,
            )
        ).answer

    on = await ask_detailed(
        "What was FY2024 revenue?",
        store=tiny_store,
        access=access,
        deal_id="deal_aurora",
        llm=doctored,
        config=CONFIG,
    )
    assert (
        on.answer.abstained
        and on.answer.abstention_reason == "Every drafted claim failed verification."
    )
    assert on.dropped and on.dropped[0].stage == "verifier"
    keep = await run(PipelineConfig(answers_log=None, drop_unverified=False))
    assert not keep.abstained and Flag.UNVERIFIED in keep.claims[0].flags
    off = await run(PipelineConfig(answers_log=None, verifier=False))
    assert not off.abstained and off.claims[0].verification is None  # the doctored claim passes


async def test_answers_are_logged_and_inspectable(tiny_store: SqliteStore, tmp_path: Path) -> None:
    log = tmp_path / "answers.jsonl"
    config = PipelineConfig(answers_log=log)
    first = await _ask(tiny_store, "What was FY2024 revenue?", config=config)
    await _ask(tiny_store, "What is the CEO's compensation package?", config=config)
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert [entry["id"] for entry in lines][0] == first.id and len(lines) == 2
    assert lines[0]["answer"]["trace"]["stage_latency_ms"]
    assert Answer.model_validate(lines[0]["answer"]) == first
    found = find_entry(log, first.id[:8])
    assert found is not None and found["id"] == first.id
    assert find_entry(log, "ans_missing") is None


async def test_answer_ids_are_deterministic(tiny_store: SqliteStore) -> None:
    one = await _ask(tiny_store, "What was FY2024 revenue?")
    two = await _ask(tiny_store, "What was FY2024 revenue?")
    other = await _ask(tiny_store, "What was FY2024 revenue?", user="u_lead")
    assert one.id == two.id != other.id


async def test_blank_question_abstains(tiny_store: SqliteStore) -> None:
    answer = await _ask(tiny_store, "   ")
    assert answer.abstained and answer.abstention_reason == "The question is empty."


async def test_general_layer_question(tiny_store: SqliteStore) -> None:
    answer = await _ask(tiny_store, "How does bidder communication work?", deal=None)
    assert not answer.abstained
    cited = {c.document_id for claim in answer.claims for c in claim.citations}
    assert cited == {"doc_playbook"}


async def test_shared_engine_fits_once_over_many_questions(tiny_store: SqliteStore) -> None:
    engine = RetrievalEngine()
    access = await tiny_store.access_for("u_analyst")
    llm = build_mock_llm()
    for question in ("What was FY2024 revenue?", "gross margin FY2024", "largest customer"):
        await ask(
            question,
            store=tiny_store,
            access=access,
            deal_id="deal_aurora",
            llm=llm,
            config=CONFIG,
            engine=engine,
        )
    assert engine.fits == 1


@pytest.mark.parametrize("doc_type", [DocType.PRESS_ARTICLE])
async def test_withdrawn_status_enum_is_what_the_pipeline_filters(
    tiny_store: SqliteStore, doc_type: DocType
) -> None:
    await add_doc(
        tiny_store,
        "doc_retracted",
        "Aurora reported FY2024 gross margin of 41.0 percent.",
        doc_type=doc_type,
        status=DocStatus.WITHDRAWN,
    )
    answer = await _ask(tiny_store, "What was the gross margin in FY2024?")
    assert all(c.document_id != "doc_retracted" for cl in answer.claims for c in cl.citations)
    assert any(Flag.WITHDRAWN in c.flags for c in answer.claims)
