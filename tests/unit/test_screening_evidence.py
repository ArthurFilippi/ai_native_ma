"""Regression tests for the evidence the deep criteria read: scoping of the retrieval, the
phrasings of the fund, ownership, market share and acquisition statements, and the deal value.

The sentences below are written by hand in the styles real documents use (an annual report, a
press release, a news item whose title and body are separate paragraphs). Nothing here reads the
generator.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

import pytest

from ainma.contracts import (
    AccessContext,
    BuyerProfile,
    BuyerType,
    CriterionResult,
    CriterionStatus,
    DocStatus,
    DocType,
    ScreeningRequest,
)
from ainma.kpi.scope import ScopedStore
from ainma.llm import MockLLM
from ainma.screening import ScreeningParams, run_screening
from ainma.screening.deep import sector_regex
from ainma.store import SqliteStore, Store
from tests.fixtures.tiny import chunk_document
from tests.fixtures_biz.data_room import DEAL_ID, load_data_room, make_doc
from tests.fixtures_biz.keyword_search import KeywordHit, keyword_search

SECTOR = "industrial components"
AS_OF = date(2025, 6, 30)
PARAMS = ScreeningParams(as_of=AS_OF)


@pytest.fixture
async def store() -> AsyncIterator[SqliteStore]:
    opened = await SqliteStore.open(":memory:")
    await load_data_room(opened)
    yield opened
    await opened.close()


def _buyer(buyer_type: BuyerType, name: str = "Acme Capital", size: float = 1000.0) -> BuyerProfile:
    financial = buyer_type is BuyerType.FINANCIAL
    return BuyerProfile(
        id="b_x",
        name=name,
        buyer_type=buyer_type,
        sectors=[SECTOR],
        geographies=["Central Europe"],
        size_eur_m=size,
        fund_vintage_year=2022 if financial else None,
    )


async def _put(
    store: SqliteStore,
    doc_id: str,
    paragraphs: list[str],
    *,
    published: date = date(2025, 5, 1),
    doc_type: DocType = DocType.COMPANY_REPORT,
    entity_id: str | None = "b_x",
    deal_id: str | None = None,
    status: DocStatus = DocStatus.CURRENT,
) -> None:
    doc = make_doc(
        doc_id,
        doc_id,
        doc_type,
        ["\n\n".join(paragraphs)],
        published,
        deal_id=deal_id,
        entity_id=entity_id,
        status=status,
    )
    await store.put_document(doc.meta, doc.pages)
    await store.put_chunks(chunk_document(doc))


async def _screen(store: SqliteStore, buyer: BuyerProfile) -> dict[str, CriterionResult]:
    result = await run_screening(
        ScreeningRequest(deal_id=DEAL_ID, stage2_top_n=50),
        store=store,
        access=await store.access_for("u_lead"),
        llm=MockLLM({}),
        buyers=[buyer],
        params=PARAMS,
        search=keyword_search,
    )
    (card,) = result.cards
    return {r.criterion_key: r for r in card.results}


# ---------------------------------------------------------------- scoped store


async def test_a_scoped_store_keeps_one_entity_and_never_writes(store: SqliteStore) -> None:
    await _put(
        store, "doc_a", ["Alpha has a market capitalisation of EUR 10 million."], entity_id="a"
    )
    await _put(
        store, "doc_b", ["Beta has a market capitalisation of EUR 20 million."], entity_id="b"
    )
    access = await store.access_for("u_lead")
    scoped = ScopedStore(store, entity_id="a")
    chunks = await scoped.candidates(access, deal_id=DEAL_ID)
    assert {c.document_id for c in chunks} == {"doc_a"}
    assert {d.id for d in await scoped.list_documents(access, DEAL_ID)} == {"doc_a"}
    with pytest.raises(PermissionError):
        await scoped.put_chunks(chunks)
    with pytest.raises(ValueError, match="exactly one"):
        ScopedStore(store)


async def test_a_deal_scope_leaves_out_the_general_layer_and_keeps_the_access_filter(
    store: SqliteStore,
) -> None:
    await _put(store, "doc_general", ["Revenue was EUR 5 million in FY2024."], entity_id="a")
    scoped = ScopedStore(store, deal_id=DEAL_ID)
    lead = await store.access_for("u_lead")
    ids = {c.document_id for c in await scoped.candidates(lead, deal_id=DEAL_ID)}
    assert "doc_general" not in ids and ids
    outsider = await store.access_for("u_outsider")
    assert await scoped.candidates(outsider, deal_id=DEAL_ID) == []


async def test_a_deal_scope_leaves_out_buyer_news_filed_in_the_deal_space(
    store: SqliteStore,
) -> None:
    await _put(
        store,
        "doc_news_buyer",
        ["Acme Capital reports revenue of EUR 900 million for FY2024."],
        entity_id="b_x",
        deal_id=DEAL_ID,
        doc_type=DocType.PRESS_ARTICLE,
    )
    await _put(
        store,
        "doc_news_deal",
        ["Aurora posts a record year."],
        entity_id=DEAL_ID,
        deal_id=DEAL_ID,
        doc_type=DocType.PRESS_ARTICLE,
    )
    scoped = ScopedStore(store, deal_id=DEAL_ID)
    ids = {
        c.document_id
        for c in await scoped.candidates(await store.access_for("u_lead"), deal_id=DEAL_ID)
    }
    assert "doc_news_buyer" not in ids and "doc_news_deal" in ids and "doc_model" in ids


async def test_other_buyers_cannot_crowd_the_buyer_out_of_a_short_result_list(
    store: SqliteStore,
) -> None:
    for i in range(12):  # twelve documents of another buyer that match the query better
        await _put(
            store,
            f"doc_decoy_{i}",
            ["Acme Capital acquisition acquired completed the acquisition of investment period."],
            entity_id="b_decoy",
        )
    await _put(
        store,
        "doc_x_pr",
        [
            "Acme Capital announces the acquisition of Brion Works, "
            "an industrial components company."
        ],
        entity_id="b_x",
        doc_type=DocType.PRESS_RELEASE,
    )

    async def top_three(
        query: str, *, store: Store, access: AccessContext, deal_id: str | None
    ) -> list[KeywordHit]:
        return (await keyword_search(query, store=store, access=access, deal_id=deal_id))[:3]

    result = await run_screening(
        ScreeningRequest(deal_id=DEAL_ID, stage2_top_n=50),
        store=store,
        access=await store.access_for("u_lead"),
        llm=MockLLM({}),
        buyers=[_buyer(BuyerType.STRATEGIC, "Acme Capital")],
        params=PARAMS,
        search=top_three,
    )
    (card,) = result.cards
    status = {r.criterion_key: r.status for r in card.results}
    assert status["recent_activity"] is CriterionStatus.MET


# ---------------------------------------------------------------- fund lifecycle


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("The investment period of the fund ends in 2028.", CriterionStatus.MET),
        ("New platform deals may be signed by the fund until 2028.", CriterionStatus.MET),
        (
            "Acme can make new platform investments until 2026, when the investment period ends.",
            CriterionStatus.NOT_MET,
        ),
        ("Investment period end: 2026.", CriterionStatus.NOT_MET),
        ("Investment period end | 2029", CriterionStatus.MET),
        (
            "The vehicle is a permanent capital structure without a fixed investment period.",
            CriterionStatus.MET,
        ),
        ("The fund holds 12 portfolio companies as of FY2024.", CriterionStatus.UNKNOWN),
    ],
)
async def test_fund_lifecycle_reads_the_usual_wordings(
    store: SqliteStore, sentence: str, expected: CriterionStatus
) -> None:
    await _put(store, "doc_x_fund", ["Acme Capital: fund summary.", sentence])
    results = await _screen(store, _buyer(BuyerType.FINANCIAL))
    assert results["fund_lifecycle"].status is expected
    if expected is not CriterionStatus.UNKNOWN:
        assert results["fund_lifecycle"].citations[0].quote in sentence or sentence in (
            results["fund_lifecycle"].citations[0].quote
        )


# ---------------------------------------------------------------- ownership


@pytest.mark.parametrize(
    ("sentences", "expected"),
    [
        (["The company is privately held."], CriterionStatus.UNKNOWN),
        (["The company is listed on a regulated exchange."], CriterionStatus.UNKNOWN),
        (["The company is privately owned and has no state shareholders."], CriterionStatus.MET),
        (["The company has no state ownership."], CriterionStatus.MET),
        (["The company has no exposure to defense contracts."], CriterionStatus.MET),
        (["The company has significant exposure to defense contracts."], CriterionStatus.NOT_MET),
        (["The company is majority owned by a sovereign wealth entity."], CriterionStatus.NOT_MET),
        (
            ["The company is privately held.", "The company has significant exposure to defence."],
            CriterionStatus.NOT_MET,
        ),
    ],
)
async def test_regulatory_fdi_needs_an_explicit_statement(
    store: SqliteStore, sentences: list[str], expected: CriterionStatus
) -> None:
    await _put(store, "doc_x_profile", ["Acme Capital: company profile.", *sentences])
    results = await _screen(store, _buyer(BuyerType.STRATEGIC))
    assert results["regulatory_fdi"].status is expected


# ---------------------------------------------------------------- market share


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Acme Capital controls 46.6% of European sales in its main segment.", "not_met"),
        (
            "Acme Capital holds a market share of 36.0 percent in its core European segment.",
            "not_met",
        ),
        ("The market share of Acme Capital in Europe was 21.7% in FY2024.", "unknown"),
        ("Acme Capital employed 4,060 people at the end of FY2024.", "unknown"),
    ],
)
async def test_antitrust_reads_the_share_wordings_and_never_guesses(
    store: SqliteStore, sentence: str, expected: str
) -> None:
    await _put(store, "doc_x_report", ["Acme Capital: annual report excerpt.", sentence])
    results = await _screen(store, _buyer(BuyerType.STRATEGIC))
    assert results["antitrust"].status.value == expected


# ---------------------------------------------------------------- acquisitions


def test_a_sector_pattern_needs_every_word_of_the_sector() -> None:
    pattern = sector_regex([SECTOR])
    assert pattern.search("a industrial components company")
    assert pattern.search("a components maker serving many large industrial customers") is None
    assert pattern.search("Draix Industries buys a medical devices company") is None
    assert sector_regex(["industrial_components"]).search("Industrial Components")
    assert sector_regex(["food and beverage"]).search("a food and beverage company")


async def test_an_acquisition_is_in_the_sector_only_if_its_own_sentence_says_so(
    store: SqliteStore,
) -> None:
    # the buyer's filler mentions the deal's sector, the target is in another one
    await _put(
        store,
        "doc_x_pr1",
        [
            "Acme Capital announces the acquisition of Brion Works, a food and beverage company. "
            "The group relies on add-on opportunities in industrial components."
        ],
        published=date(2025, 4, 8),
        doc_type=DocType.PRESS_RELEASE,
    )
    results = await _screen(store, _buyer(BuyerType.STRATEGIC))
    assert results["recent_activity"].status is CriterionStatus.NOT_MET


async def test_the_buyers_own_name_is_not_the_targets_sector(store: SqliteStore) -> None:
    await _put(
        store,
        "doc_x_pr1",
        ["Draix Industries announces the acquisition of Draund Tech, a medical devices company."],
        published=date(2025, 4, 8),
        doc_type=DocType.PRESS_RELEASE,
    )
    buyer = _buyer(BuyerType.STRATEGIC, "Draix Industries")
    assert (await _screen(store, buyer))["recent_activity"].status is CriterionStatus.NOT_MET


async def test_a_news_item_with_title_and_body_in_separate_chunks_is_read_as_one_acquisition(
    store: SqliteStore,
) -> None:
    await _put(
        store,
        "doc_news_1",
        [
            "Acme Capital completes acquisition of Fynar Partners",
            "Acme Capital completes acquisition of Fynar Partners. "
            "The target is a industrial components company.",
        ],
        published=date(2024, 7, 23),
        doc_type=DocType.PRESS_ARTICLE,
    )
    results = await _screen(store, _buyer(BuyerType.STRATEGIC))
    assert results["recent_activity"].status is CriterionStatus.MET
    (citation, *_) = results["recent_activity"].citations
    assert "The target is a industrial components company" in citation.quote
    assert results["integration_bandwidth"].status is CriterionStatus.MET


async def test_an_acquisition_outside_the_window_does_not_count_as_recent(
    store: SqliteStore,
) -> None:
    await _put(
        store,
        "doc_x_pr_old",
        [
            "Acme Capital announces the acquisition of Fynar Partners, "
            "a industrial components company."
        ],
        published=date(2022, 5, 1),
        doc_type=DocType.PRESS_RELEASE,
    )
    results = await _screen(store, _buyer(BuyerType.STRATEGIC))
    assert results["recent_activity"].status is CriterionStatus.NOT_MET
    # A `met` verdict of the bandwidth rule rests on zero recent reports: it still cites the
    # newest report found, outside the window, so that no verdict stands without evidence.
    bandwidth = results["integration_bandwidth"]
    assert bandwidth.status is CriterionStatus.MET
    assert len(bandwidth.citations) == 1
    assert "outside the window" in bandwidth.rationale


# ---------------------------------------------------------------- deal value


async def test_the_stated_deal_value_sizes_the_cheque_and_a_superseded_draft_is_ignored(
    store: SqliteStore,
) -> None:
    await _put(
        store,
        "doc_cim_value",
        [
            "On a cash-free and debt-free basis the business is priced at EUR 197.1 million.",
            "Shareholders would receive EUR 169.2 million for their shares after net debt.",
            "A seller walking away pays 3.0 percent of the equity value under the SPA.",
        ],
        entity_id=None,
        deal_id=DEAL_ID,
        doc_type=DocType.DEAL_DOCUMENT,
    )
    await _put(
        store,
        "doc_spa_draft_value",
        ["The transaction values the company at an enterprise value of EUR 188.6 million."],
        entity_id=None,
        deal_id=DEAL_ID,
        doc_type=DocType.DEAL_DOCUMENT,
        status=DocStatus.SUPERSEDED,
    )
    results = await _screen(store, _buyer(BuyerType.FINANCIAL, size=1000.0))
    ticket = results["ticket_fit"]
    assert ticket.status is CriterionStatus.MET
    assert "EUR 169.2m" in ticket.rationale and "197.1" in ticket.rationale
    assert (
        "188.6" not in ticket.rationale and "(parameter)" not in ticket.rationale.split("= EUR")[0]
    )
    quotes = " ".join(c.quote for c in ticket.citations)
    assert "197.1" in quotes and "169.2" in quotes
    strategic = await _screen(store, _buyer(BuyerType.STRATEGIC, size=400.0))
    assert strategic["ev_ratio"].status is CriterionStatus.MET  # 49%: transformational
    assert "transformational" in strategic["ev_ratio"].rationale


async def test_an_enterprise_value_alone_gives_the_cheque_through_the_documented_share(
    store: SqliteStore,
) -> None:
    await _put(
        store,
        "doc_spa_value",
        ["The transaction values the company at an enterprise value of EUR 200.0m."],
        entity_id=None,
        deal_id=DEAL_ID,
        doc_type=DocType.DEAL_DOCUMENT,
    )
    ticket = (await _screen(store, _buyer(BuyerType.FINANCIAL, size=1000.0)))["ticket_fit"]
    assert "equity cheque at 50% of EV (parameter) = EUR 100m" in ticket.rationale
    assert ticket.status is CriterionStatus.MET


async def test_without_a_stated_value_the_ebitda_and_the_parameters_size_the_deal(
    store: SqliteStore,
) -> None:
    ticket = (await _screen(store, _buyer(BuyerType.FINANCIAL, size=1000.0)))["ticket_fit"]
    assert "EV/EBITDA (parameter)" in ticket.rationale and "EUR 126m" in ticket.rationale
