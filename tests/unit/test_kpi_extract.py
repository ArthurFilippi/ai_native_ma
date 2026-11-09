from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from ainma.contracts import KpiValue
from ainma.kpi import extract_kpis
from ainma.kpi.definitions import DEFAULT_PERIODS, kpi_definitions
from ainma.llm import MockLLM
from ainma.store import SqliteStore
from tests.fixtures_biz.data_room import DEAL_ID, PERIODS, ROWS, load_data_room
from tests.fixtures_biz.keyword_search import keyword_search

REL_TOL = 0.005  # the acceptance tolerance of the evaluation plan


@pytest.fixture
async def store() -> AsyncIterator[SqliteStore]:
    opened = await SqliteStore.open(":memory:")
    await load_data_room(opened)
    yield opened
    await opened.close()


async def _extract(store: SqliteStore, user: str = "u_lead") -> list[KpiValue]:
    access = await store.access_for(user)
    return await extract_kpis(
        DEAL_ID, store=store, access=access, llm=MockLLM({}), search=keyword_search
    )


def _by_key(values: list[KpiValue]) -> dict[tuple[str, str], KpiValue]:
    return {(v.kpi_id, v.period): v for v in values}


async def test_one_value_per_definition_and_period_in_a_stable_order(store: SqliteStore) -> None:
    values = await _extract(store)
    expected = [(d.id, p) for d in kpi_definitions() for p in DEFAULT_PERIODS]
    assert [(v.kpi_id, v.period) for v in values] == expected
    assert values == await _extract(store)


async def test_extracted_kpis_match_the_known_table(store: SqliteStore) -> None:
    by_key = _by_key(await _extract(store))
    for kpi_id, row in ROWS.items():
        for period, truth in zip(PERIODS, row, strict=True):
            value = by_key[(kpi_id, period)]
            assert value.status == "sourced", (kpi_id, period)
            assert value.value == pytest.approx(truth, rel=REL_TOL), (kpi_id, period)


async def test_computed_kpis_expose_their_inputs_and_follow_the_formulas(
    store: SqliteStore,
) -> None:
    by_key = _by_key(await _extract(store))
    gross_profit = by_key[("gross_profit", "FY2024")]
    assert gross_profit.status == "computed"
    assert gross_profit.formula_inputs == {"revenue": 182.4, "cogs": 112.2}
    assert gross_profit.value == pytest.approx(70.2)
    gross_margin = by_key[("gross_margin", "FY2024")]
    assert gross_margin.status == "computed"
    assert gross_margin.value == pytest.approx(70.2 / 182.4 * 100)
    assert gross_margin.formula_inputs["gross_profit"] == pytest.approx(70.2)
    net_debt = by_key[("net_debt", "FY2023")]
    assert net_debt.value == pytest.approx(52.0 - 16.2)
    leverage = by_key[("leverage", "FY2023")]
    assert leverage.value == pytest.approx((52.0 - 16.2) / 28.9)
    assert by_key[("free_cash_flow", "FY2020")].value == pytest.approx(20.0 - 8.0)


async def test_sourced_citations_point_at_the_exact_span_and_contain_the_value(
    store: SqliteStore,
) -> None:
    access = await store.access_for("u_lead")
    sourced = [v for v in await _extract(store) if v.status == "sourced"]
    assert sourced
    for value in sourced:
        (citation,) = value.citations
        page = await store.get_page(citation.document_id, citation.page, access)
        assert page is not None
        assert page[citation.char_start : citation.char_end] == citation.quote
        chunk = await store.get_chunk(citation.chunk_id, access)
        assert chunk is not None and citation.quote in chunk.text
        assert value.value is not None


async def test_deal_document_wins_over_a_conflicting_press_article(store: SqliteStore) -> None:
    value = _by_key(await _extract(store))[("revenue", "FY2024")]
    assert value.value == 182.4
    assert value.citations[0].document_id in {"doc_model", "doc_cim"}


async def test_unknown_period_and_missing_inputs_stay_missing(store: SqliteStore) -> None:
    access = await store.access_for("u_lead")
    values = await extract_kpis(
        DEAL_ID,
        store=store,
        access=access,
        llm=MockLLM({}),
        periods=["FY2031"],
        search=keyword_search,
    )
    assert {v.status for v in values} == {"missing"}
    assert all(v.value is None and not v.citations for v in values)


async def test_a_stated_value_is_used_when_the_inputs_are_not_available(
    store: SqliteStore,
) -> None:
    """Customer concentration is only stated in prose, with a period after the number."""
    by_key = _by_key(await _extract(store))
    value = by_key[("customer_concentration", "FY2024")]
    assert (value.status, value.value) == ("sourced", 17.0)
    assert by_key[("customer_concentration", "FY2023")].status == "missing"


async def test_a_user_without_access_gets_nothing(store: SqliteStore) -> None:
    values = await _extract(store, "u_outsider")
    assert {v.status for v in values} == {"missing"}


async def test_restricting_kpi_ids_reads_dependencies_but_returns_only_the_request(
    store: SqliteStore,
) -> None:
    access = await store.access_for("u_lead")
    values = await extract_kpis(
        DEAL_ID,
        store=store,
        access=access,
        llm=MockLLM({}),
        periods=["FY2024"],
        kpi_ids=["gross_margin", "ebitda"],
        search=keyword_search,
    )
    assert [v.kpi_id for v in values] == ["gross_margin", "ebitda"]
    assert values[0].status == "computed" and values[1].value == 31.5
    with pytest.raises(ValueError, match="unknown KPI ids"):
        await extract_kpis(
            DEAL_ID,
            store=store,
            access=access,
            llm=MockLLM({}),
            kpi_ids=["nope"],
            search=keyword_search,
        )
