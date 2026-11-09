from __future__ import annotations

import pytest

from ainma.contracts import BuyerProfile, BuyerType, CriterionStatus, ScreeningFilters
from ainma.screening.criteria import PREFILTER_KEYS, build_criteria
from ainma.screening.evidence import sentence_around
from ainma.screening.prefilter import prefilter_results, sectors_overlap

BUYER = BuyerProfile(
    id="b_x",
    name="X Partners",
    buyer_type=BuyerType.FINANCIAL,
    sectors=["industrial components", "logistics"],
    geographies=["DACH", "Nordics"],
    size_eur_m=1500.0,
)


def _status(filters: ScreeningFilters, sectors: list[str]) -> dict[str, CriterionStatus]:
    return {r.criterion_key: r.status for r in prefilter_results(BUYER, filters, sectors)}


def test_every_prefilter_key_has_a_result_in_order() -> None:
    results = prefilter_results(BUYER, ScreeningFilters(), ["industrial components"])
    assert [r.criterion_key for r in results] == list(PREFILTER_KEYS)


def test_filters_that_are_not_requested_stay_unknown_never_met() -> None:
    status = _status(ScreeningFilters(), ["industrial components"])
    assert status["buyer_type"] is CriterionStatus.UNKNOWN
    assert status["geography"] is CriterionStatus.UNKNOWN
    assert status["size_range"] is CriterionStatus.UNKNOWN
    assert status["sector_focus"] is CriterionStatus.MET


def test_matching_and_failing_filters() -> None:
    ok = ScreeningFilters(
        buyer_types=[BuyerType.FINANCIAL],
        geographies=["dach"],
        min_size_eur_m=1000.0,
        max_size_eur_m=2000.0,
    )
    assert set(_status(ok, ["industrial components"]).values()) == {CriterionStatus.MET}
    bad = ScreeningFilters(
        buyer_types=[BuyerType.STRATEGIC],
        geographies=["Iberia"],
        min_size_eur_m=2000.0,
    )
    status = _status(bad, ["software"])
    assert set(status.values()) == {CriterionStatus.NOT_MET}


def test_size_bounds_are_inclusive_and_one_sided() -> None:
    assert _status(ScreeningFilters(max_size_eur_m=1500.0), ["logistics"])["size_range"] is (
        CriterionStatus.MET
    )
    assert _status(ScreeningFilters(min_size_eur_m=1500.1), ["logistics"])["size_range"] is (
        CriterionStatus.NOT_MET
    )


@pytest.mark.parametrize(
    ("own", "target", "match"),
    [
        (["industrial components"], ["industrial components"], True),
        (["industrials"], ["industrial components"], True),
        (["industrial"], ["industrial components"], True),
        (["enterprise software"], ["industrial components"], False),
        (["healthcare services"], ["healthcare"], True),
        ([], ["industrial components"], False),
    ],
)
def test_sector_matching(own: list[str], target: list[str], match: bool) -> None:
    assert bool(sectors_overlap(own, target)) is match


def test_build_criteria_applies_weights_and_rejects_unknown_keys() -> None:
    criteria = {c.key: c for c in build_criteria({"ticket_fit": 7.0})}
    assert criteria["ticket_fit"].weight == 7.0 and criteria["ticket_fit"].dealbreaker
    assert criteria["ev_ratio"].dealbreaker and not criteria["fund_lifecycle"].dealbreaker
    with pytest.raises(ValueError, match="unknown criterion keys"):
        build_criteria({"ticket_fitt": 1.0})


def test_sentence_around_returns_a_substring_bounded_by_sentence_or_line() -> None:
    text = "First sentence here. Fund III has commitments of EUR 1.8 billion. Third one.\nNext line"
    start = text.index("EUR 1.8")
    left, right = sentence_around(text, start, start + 7)
    assert text[left:right] == "Fund III has commitments of EUR 1.8 billion."
    start = text.index("Next")
    left, right = sentence_around(text, start, start + 4)
    assert text[left:right] == "Next line"
