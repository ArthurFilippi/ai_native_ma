"""End to end screening on the six buyer mini universe (offline, deterministic)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

import pytest

from ainma.contracts import (
    BuyerProfile,
    CriterionStatus,
    ScreeningFilters,
    ScreeningRequest,
    ScreeningResult,
)
from ainma.llm import MockLLM
from ainma.screening import (
    BuyerUniverseUnavailable,
    ScreeningParams,
    run_screening,
)
from ainma.store import SqliteStore
from tests.fixtures_biz.data_room import DEAL_ID
from tests.fixtures_biz.keyword_search import keyword_search
from tests.fixtures_biz.universe import load_universe

DEEP_KEYS = {
    "ticket_fit",
    "ev_ratio",
    "fund_lifecycle",
    "recent_activity",
    "integration_bandwidth",
    "antitrust",
    "regulatory_fdi",
}


@pytest.fixture
async def store() -> AsyncIterator[SqliteStore]:
    opened = await SqliteStore.open(":memory:")
    yield opened
    await opened.close()


@pytest.fixture
async def buyers(store: SqliteStore) -> list[BuyerProfile]:
    return await load_universe(store)


async def _run(
    store: SqliteStore,
    buyers: list[BuyerProfile],
    *,
    request: ScreeningRequest | None = None,
    params: ScreeningParams | None = None,
    user: str = "u_lead",
) -> ScreeningResult:
    return await run_screening(
        request
        or ScreeningRequest(deal_id=DEAL_ID, filters=ScreeningFilters(geographies=["DACH"])),
        store=store,
        access=await store.access_for(user),
        llm=MockLLM({}),
        buyers=buyers,
        params=params,
        search=keyword_search,
    )


def _status(result: ScreeningResult, buyer_id: str) -> dict[str, CriterionStatus]:
    (card,) = [c for c in result.cards if c.buyer.id == buyer_id]
    return {r.criterion_key: r.status for r in card.results}


async def test_one_deal_yields_an_unknown_criterion_and_a_dealbreaker(
    store: SqliteStore, buyers: list[BuyerProfile]
) -> None:
    result = await _run(store, buyers)
    by_id = {c.buyer.id: c for c in result.cards}
    assert by_id["b_tiny"].dealbreakers == ["ticket_fit"]
    assert by_id["b_tiny"].rank == max(c.rank for c in result.cards if c.rank)  # after all others
    lonely = _status(result, "b_lonely")
    assert lonely["fund_lifecycle"] is CriterionStatus.UNKNOWN
    assert lonely["antitrust"] is CriterionStatus.UNKNOWN
    assert by_id["b_lonely"].coverage < 1.0
    assert ScreeningResult.model_validate_json(result.model_dump_json()) == result


async def test_stage_one_failures_are_shown_unscored_and_unranked(
    store: SqliteStore, buyers: list[BuyerProfile]
) -> None:
    result = await _run(store, buyers)
    failed = result.cards[-1]
    assert failed.buyer.id == "b_software" and not failed.stage1_passed
    assert failed.rank is None and failed.score is None
    assert {r.criterion_key for r in failed.results} == {
        "buyer_type",
        "sector_focus",
        "geography",
        "size_range",
    }
    assert _status(result, "b_software")["sector_focus"] is CriterionStatus.NOT_MET
    assert [c.rank for c in result.cards if c.rank] == [1, 2, 3, 4, 5]


async def test_criteria_apply_to_the_right_buyer_type(
    store: SqliteStore, buyers: list[BuyerProfile]
) -> None:
    result = await _run(store, buyers)
    financial = set(_status(result, "b_nordvik"))
    strategic = set(_status(result, "b_orbis"))
    assert {"ticket_fit", "fund_lifecycle"} <= financial
    assert not {"ev_ratio", "integration_bandwidth"} & financial
    assert {"ev_ratio", "integration_bandwidth"} <= strategic
    assert not {"ticket_fit", "fund_lifecycle"} & strategic


async def test_documented_rules_give_the_expected_verdicts(
    store: SqliteStore, buyers: list[BuyerProfile]
) -> None:
    result = await _run(store, buyers)
    nordvik = _status(result, "b_nordvik")
    assert nordvik["ticket_fit"] is CriterionStatus.MET  # 126 / 1800 = 7.0%
    assert nordvik["fund_lifecycle"] is CriterionStatus.MET  # ends June 2028
    assert nordvik["recent_activity"] is CriterionStatus.MET
    assert nordvik["antitrust"] is CriterionStatus.UNKNOWN  # no share data: never guessed
    assert nordvik["regulatory_fdi"] is CriterionStatus.UNKNOWN
    assert _status(result, "b_tiny")["ticket_fit"] is CriterionStatus.NOT_MET  # 63%
    orbis = _status(result, "b_orbis")
    assert orbis["ev_ratio"] is CriterionStatus.MET
    assert orbis["antitrust"] is CriterionStatus.MET  # 12 + 15 = 27 < 35
    assert (
        orbis["regulatory_fdi"] is CriterionStatus.MET
    )  # "no state ownership" is not a constraint
    granite = _status(result, "b_granite")
    assert granite["ev_ratio"] is CriterionStatus.MET  # 50.4%: transformational, still feasible
    assert granite["integration_bandwidth"] is CriterionStatus.NOT_MET  # three acquisitions
    assert granite["antitrust"] is CriterionStatus.NOT_MET  # 30 + 15 = 45
    assert granite["regulatory_fdi"] is CriterionStatus.NOT_MET
    (granite_card,) = [c for c in result.cards if c.buyer.id == "b_granite"]
    ev = {r.criterion_key: r for r in granite_card.results}["ev_ratio"]
    assert "transformational" in ev.rationale


async def test_no_deep_verdict_without_a_citation(
    store: SqliteStore, buyers: list[BuyerProfile]
) -> None:
    result = await _run(store, buyers)
    checked = 0
    for card in result.cards:
        for r in card.results:
            if r.criterion_key in DEEP_KEYS and r.status is not CriterionStatus.UNKNOWN:
                assert r.citations, (card.buyer.id, r.criterion_key)
                checked += 1
            if r.status is CriterionStatus.UNKNOWN:
                assert not r.citations
    assert checked >= 10


async def test_citations_are_verbatim_spans_of_their_pages(
    store: SqliteStore, buyers: list[BuyerProfile]
) -> None:
    access = await store.access_for("u_lead")
    result = await _run(store, buyers)
    count = 0
    for card in result.cards:
        for r in card.results:
            for citation in r.citations:
                page = await store.get_page(citation.document_id, citation.page, access)
                assert page is not None
                assert page[citation.char_start : citation.char_end] == citation.quote
                count += 1
    assert count > 15


async def test_weight_override_changes_the_ranking(
    store: SqliteStore, buyers: list[BuyerProfile]
) -> None:
    default = await _run(store, buyers)
    request = ScreeningRequest(
        deal_id=DEAL_ID,
        filters=ScreeningFilters(geographies=["DACH"]),
        weights={"recent_activity": 0.0, "fund_lifecycle": 0.0},
    )
    changed = await _run(store, buyers, request=request)
    order = lambda r: [c.buyer.id for c in r.cards if c.rank]  # noqa: E731
    assert order(default)[:3] == ["b_orbis", "b_nordvik", "b_lonely"]
    assert order(changed)[:3] == ["b_orbis", "b_lonely", "b_nordvik"]
    assert {c.key: c.weight for c in changed.criteria}["recent_activity"] == 0.0


async def test_stage_two_only_evaluates_the_top_n(
    store: SqliteStore, buyers: list[BuyerProfile]
) -> None:
    request = ScreeningRequest(
        deal_id=DEAL_ID, filters=ScreeningFilters(geographies=["DACH"]), stage2_top_n=2
    )
    result = await _run(store, buyers, request=request)
    evaluated = [
        c.buyer.id
        for c in result.cards
        if c.stage1_passed
        and any(
            r.status is not CriterionStatus.UNKNOWN and r.criterion_key in DEEP_KEYS
            for r in c.results
        )
    ]
    assert sorted(evaluated) == ["b_granite", "b_lonely"]
    (nordvik,) = [c for c in result.cards if c.buyer.id == "b_nordvik"]
    deep = [r for r in nordvik.results if r.criterion_key in DEEP_KEYS]
    assert deep and all("Not evaluated" in r.rationale for r in deep)


async def test_ev_ratio_above_sixty_percent_is_a_dealbreaker_and_conflicts_are_flagged(
    store: SqliteStore, buyers: list[BuyerProfile]
) -> None:
    shrunk = [
        b.model_copy(update={"size_eur_m": 300.0}) if b.id == "b_granite" else b for b in buyers
    ]
    result = await _run(store, shrunk)
    (card,) = [c for c in result.cards if c.buyer.id == "b_granite"]
    assert card.dealbreakers == ["ev_ratio"]  # 252 / 300 = 84%
    ev = {r.criterion_key: r for r in card.results}["ev_ratio"]
    assert ev.status is CriterionStatus.NOT_MET
    assert ev.conflicting_evidence  # the annual report states EUR 500 million, the profile 300
    assert card.rank == max(c.rank for c in result.cards if c.rank)


async def test_investment_period_that_is_too_short_is_not_met(
    store: SqliteStore, buyers: list[BuyerProfile]
) -> None:
    result = await _run(store, buyers, params=ScreeningParams(as_of=date(2027, 6, 1)))
    assert _status(result, "b_nordvik")["fund_lifecycle"] is CriterionStatus.NOT_MET


async def test_without_deal_ebitda_the_sized_criteria_are_unknown(
    store: SqliteStore, buyers: list[BuyerProfile]
) -> None:
    for doc in await store.list_documents(await store.access_for("u_lead"), DEAL_ID):
        if doc.id in {"doc_model", "doc_cim"}:
            await store.put_document(doc, ["SYNTHETIC DOCUMENT, fictional data."] * doc.n_pages)
    result = await _run(store, buyers)
    assert _status(result, "b_nordvik")["ticket_fit"] is CriterionStatus.UNKNOWN
    assert _status(result, "b_orbis")["ev_ratio"] is CriterionStatus.UNKNOWN


async def test_a_user_outside_the_deal_gets_a_lookup_error(
    store: SqliteStore, buyers: list[BuyerProfile]
) -> None:
    with pytest.raises(LookupError):
        await _run(store, buyers, user="u_outsider")


async def test_request_errors_are_loud(store: SqliteStore, buyers: list[BuyerProfile]) -> None:
    with pytest.raises(ValueError, match="unknown criterion keys"):
        await _run(store, buyers, request=ScreeningRequest(deal_id=DEAL_ID, weights={"nope": 1.0}))
    with pytest.raises(BuyerUniverseUnavailable):
        await run_screening(
            ScreeningRequest(deal_id=DEAL_ID),
            store=store,
            access=await store.access_for("u_lead"),
            llm=MockLLM({}),
            search=keyword_search,
        )
