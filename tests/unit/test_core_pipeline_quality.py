"""Regression tests for the quality fixes of the core pipeline, on the tiny corpus.

Each test names the failure it prevents: other companies polluting an answer, a superseded
source silently left out, the writer window hiding a relevant press article, a table row or an
undated source being rejected for lacking a year.
"""

from __future__ import annotations

from datetime import date

from ainma.contracts import Answer, ClaimStatus, DocStatus, DocType, Flag
from ainma.llm import build_mock_llm
from ainma.pipeline import PipelineConfig, abstain, ask
from ainma.pipeline.verify import numeric_match
from ainma.retrieval import RetrievalConfig, RetrievalEngine, search_detailed
from ainma.store import SqliteStore
from tests.fixtures_core.scripted import add_doc

CONFIG = PipelineConfig(answers_log=None)
TABLE = "EUR m | FY2023 | FY2024\nRevenue | 168.0 | 182.4"


async def _ask(store: SqliteStore, question: str) -> Answer:
    access = await store.access_for("u_analyst")
    return await ask(
        question,
        store=store,
        access=access,
        deal_id="deal_aurora",
        llm=build_mock_llm(),
        config=CONFIG,
    )


async def test_buyer_documents_about_other_companies_never_answer_a_deal_question(
    tiny_store: SqliteStore,
) -> None:
    await add_doc(
        tiny_store,
        "doc_buyer_27_report",
        "Tarnar Industries: annual report excerpt\n\n"
        "Turnover climbed to EUR 1,053.5m over fiscal 2024.\n\n"
        "Tarnar Industries generated revenue of EUR 193.4m in FY2024.",
        doc_type=DocType.COMPANY_REPORT,
        deal_id=None,
    )
    answer = await _ask(tiny_store, "What was Aurora's FY2024 revenue?")
    cited = {c.document_id for claim in answer.claims for c in claim.citations}
    assert "doc_buyer_27_report" not in cited
    assert cited >= {"doc_cim"}


async def test_a_superseded_source_is_flagged_not_left_out(tiny_store: SqliteStore) -> None:
    await add_doc(
        tiny_store,
        "doc_spa_exec",
        "Project Aurora share purchase agreement.\n\n"
        "The transaction values the company at an enterprise value of EUR 281.6m.",
        doc_type=DocType.SIGNED_AGREEMENT,
        published_on=date(2025, 5, 20),
    )
    await add_doc(
        tiny_store,
        "doc_spa_draft",
        "Project Aurora share purchase agreement, draft.\n\n"
        "The transaction values the company at an enterprise value of EUR 265.5m.",
        doc_type=DocType.DEAL_DOCUMENT,
        published_on=date(2025, 4, 10),
        status=DocStatus.SUPERSEDED,
        superseded_by="doc_spa_exec",
    )
    answer = await _ask(tiny_store, "What is the enterprise value of Aurora?")
    sourced = [c for c in answer.claims if c.status is ClaimStatus.SOURCED]
    by_doc = {c.citations[0].document_id: c for c in sourced}
    assert (
        "281.6" in by_doc["doc_spa_exec"].text
        and Flag.SUPERSEDED not in by_doc["doc_spa_exec"].flags
    )
    assert (
        "265.5" in by_doc["doc_spa_draft"].text and Flag.SUPERSEDED in by_doc["doc_spa_draft"].flags
    )
    assert not answer.contradictions


async def test_search_lists_the_superseded_passages_below_the_top_k(
    tiny_store: SqliteStore,
) -> None:
    await add_doc(
        tiny_store,
        "doc_spa_exec",
        "The transaction values the company at an enterprise value of EUR 281.6m.",
        doc_type=DocType.SIGNED_AGREEMENT,
    )
    await add_doc(
        tiny_store,
        "doc_spa_draft",
        "The transaction values the company at an enterprise value of EUR 265.5m.",
        status=DocStatus.SUPERSEDED,
        superseded_by="doc_spa_exec",
    )
    access = await tiny_store.access_for("u_analyst")
    result = await search_detailed(
        "enterprise value of Aurora",
        store=tiny_store,
        access=access,
        deal_id="deal_aurora",
        config=RetrievalConfig(top_k=1),
        engine=RetrievalEngine(),
    )
    assert [h.document.id for h in result.hits] == ["doc_spa_exec"]
    assert "doc_spa_draft" in {h.document.id for h in result.superseded}


async def test_the_press_article_next_to_the_cim_still_reaches_the_writer(
    tiny_store: SqliteStore,
) -> None:
    access = await tiny_store.access_for("u_analyst")
    result = await search_detailed(
        "What was Aurora's FY2024 revenue?",
        store=tiny_store,
        access=access,
        deal_id="deal_aurora",
        config=RetrievalConfig(top_k=20),
        engine=RetrievalEngine(),
    )
    window = abstain.writer_window(result.hits, 3)
    assert {h.document.id for h in window} >= {"doc_cim", "doc_news_17"}
    # relevance chooses the window, trust orders it: the CIM comes before the trade press
    order = [h.document.id for h in window]
    assert order.index("doc_cim") < order.index("doc_news_17")


def test_a_table_row_takes_its_year_from_the_chunk_header() -> None:
    row = "Revenue | 168.0 | 182.4"
    claim = "Aurora revenue for FY2024 was EUR 182.4 million."
    assert not numeric_match(claim, row)[0]  # alone the row says no year
    assert numeric_match(claim, row, TABLE)[0]


def test_a_quote_that_states_another_year_is_not_rescued_by_the_context() -> None:
    quote = "Net revenue for FY2023 was EUR 182.4 million."
    context = f"{quote} Outlook for FY2024 is stable."
    assert not numeric_match("Aurora revenue for FY2024 was EUR 182.4 million.", quote, context)[0]


def test_an_undated_source_leaves_the_year_of_the_claim_unchecked() -> None:
    quote = "Fynex is reported to manage roughly EUR 680 million."
    claim = "Fynex assets under management for FY2024 was EUR 680.0 million."
    assert numeric_match(claim, quote, quote)[0]
    assert not numeric_match(claim.replace("680.0", "690.0"), quote, quote)[0]
