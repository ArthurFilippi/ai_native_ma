"""The one scoring function reproduces the shared vectors (the TypeScript twin uses them too)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ainma.contracts import (
    BuyerCard,
    BuyerProfile,
    BuyerType,
    Criterion,
    CriterionResult,
    CriterionStatus,
)
from ainma.screening.scoring import score_cards
from tests.conftest import FIXTURES

TOL = 1e-6
VECTORS: dict[str, Any] = json.loads((FIXTURES / "scoring_vectors.json").read_text("utf-8"))


def _criteria() -> list[Criterion]:
    return [
        Criterion(
            key=c["key"],
            label=c["key"],
            kind="deep",
            weight=c["weight"],
            dealbreaker=c["dealbreaker"],
        )
        for c in VECTORS["criteria"]
    ]


def _profile(buyer_id: str) -> BuyerProfile:
    return BuyerProfile(
        id=buyer_id,
        name=buyer_id,
        buyer_type=BuyerType.FINANCIAL,
        sectors=["industrial components"],
        geographies=["DACH"],
        size_eur_m=1000.0,
    )


def _card(buyer_id: str, statuses: dict[str, str], *, passed: bool = True) -> BuyerCard:
    results = [
        CriterionResult(
            criterion_key=key,
            status=CriterionStatus(status),
            rationale="vector",
        )
        for key, status in statuses.items()
    ]
    return BuyerCard(buyer=_profile(buyer_id), stage1_passed=passed, results=results)


def _cards() -> list[BuyerCard]:
    return [_card(buyer_id, statuses) for buyer_id, statuses in VECTORS["buyers"].items()]


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["name"])
def test_matches_shared_vectors(case: dict[str, Any]) -> None:
    expected = case["expected"]
    scored = score_cards(_criteria(), _cards(), case["weight_overrides"])
    assert [c.buyer.id for c in scored] == expected["ranking"]
    assert [c.rank for c in scored] == list(range(1, len(scored) + 1))
    for card in scored:
        want = expected["cards"][card.buyer.id]
        if want["score"] is None:
            assert card.score is None
        else:
            assert card.score == pytest.approx(want["score"], abs=TOL)
        assert card.coverage == pytest.approx(want["coverage"], abs=TOL)
        assert card.dealbreakers == want["dealbreakers"]
        assert set(card.contributions) == set(want["contributions"])
        for key, value in want["contributions"].items():
            assert card.contributions[key] == pytest.approx(value, abs=TOL)
        if card.score is not None:
            assert sum(card.contributions.values()) == pytest.approx(card.score, abs=TOL)


def test_weight_override_changes_the_ranking() -> None:
    default = score_cards(_criteria(), _cards(), {})
    heavy = score_cards(_criteria(), _cards(), {"sector_focus": 6.0})
    assert [c.buyer.id for c in default] != [c.buyer.id for c in heavy]


def test_input_cards_are_not_mutated() -> None:
    cards = _cards()
    score_cards(_criteria(), cards, {})
    assert all(c.score is None and c.rank is None for c in cards)


def test_stage1_failures_are_unscored_unranked_and_listed_last() -> None:
    cards = [
        _card("b_z", {"ticket_fit": "met"}, passed=False),
        _card("b_a", {"ticket_fit": "met"}),
        _card("b_c", {"ticket_fit": "not_met"}),
    ]
    scored = score_cards(_criteria(), cards, {})
    assert [c.buyer.id for c in scored] == ["b_a", "b_c", "b_z"]
    failed = scored[-1]
    assert failed.rank is None and failed.score is None and failed.coverage == 0.0
    assert failed.contributions == {} and failed.dealbreakers == []


def test_criterion_without_result_is_not_applicable() -> None:
    """A strategic buyer has no ticket_fit result: its weight leaves the coverage denominator."""
    card = _card("b_s", {"sector_focus": "met", "recent_activity": "met"})
    (scored,) = score_cards(_criteria(), [card], {})
    assert scored.coverage == pytest.approx(1.0, abs=TOL)
    assert scored.score == pytest.approx(1.0, abs=TOL)
    assert scored.contributions["ticket_fit"] == 0.0


def test_ties_are_broken_by_coverage_then_buyer_id() -> None:
    cards = [
        _card("b_2", {"sector_focus": "met", "recent_activity": "unknown"}),
        _card("b_1", {"sector_focus": "met", "recent_activity": "unknown"}),
        _card("b_0", {"sector_focus": "met", "recent_activity": "met"}),
    ]
    scored = score_cards(_criteria(), cards, {})
    assert [c.buyer.id for c in scored] == ["b_0", "b_1", "b_2"]


def test_negative_weight_and_duplicate_results_are_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        score_cards(_criteria(), _cards(), {"ticket_fit": -1.0})
    duplicated = _card("b_x", {"ticket_fit": "met"})
    duplicated.results.append(duplicated.results[0])
    with pytest.raises(ValueError, match="duplicate"):
        score_cards(_criteria(), [duplicated], {})


def test_scored_card_round_trips_through_json() -> None:
    scored = score_cards(_criteria(), _cards(), {})
    for card in scored:
        assert BuyerCard.model_validate_json(card.model_dump_json()) == card
