"""A sentence becomes a typed change of the screening request (D98)."""

from __future__ import annotations

from ainma.contracts import BuyerType, ScreeningRequest
from ainma.llm import build_mock_llm
from ainma.screening.refine import refine_request

REGIONS = ["DACH", "France", "Central Europe", "Nordics"]


async def test_sentence_sets_type_region_size_and_emphasis() -> None:
    current = ScreeningRequest(deal_id="deal_aurora")
    outcome = await refine_request(
        "Only private equity funds in DACH or France, above EUR 500m, prefer recent acquirers",
        current,
        geographies=REGIONS,
        llm=build_mock_llm(),
    )
    f = outcome.request.filters
    assert f.buyer_types == [BuyerType.FINANCIAL]
    assert f.geographies == ["DACH", "France"]
    assert f.min_size_eur_m == 500.0 and f.max_size_eur_m is None
    assert outcome.request.weights["recent_activity"] > 0
    assert "prefer recent acquirers" in outcome.understood


async def test_billions_and_upper_bound_and_unknown_words() -> None:
    current = ScreeningRequest(deal_id="deal_aurora")
    outcome = await refine_request(
        "strategic buyers under 2.5bn, no idea otherwise",
        current,
        geographies=REGIONS,
        llm=build_mock_llm(),
    )
    assert outcome.request.filters.max_size_eur_m == 2500.0
    assert outcome.request.filters.buyer_types == [BuyerType.STRATEGIC]
    assert outcome.request.deal_id == "deal_aurora"
