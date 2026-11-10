"""Spearman of a buyer order against the truth score, the measure of D86 (hand computed)."""

from __future__ import annotations

import pytest

from ainma.evaluation.metrics.screening import ranking_agreement, spearman, true_scores


def test_spearman_hand_examples() -> None:
    assert spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)
    assert spearman([1, 2, 3], [30, 20, 10]) == pytest.approx(-1.0)
    # ties take the average rank: ranks (1, 2.5, 2.5) against (1, 2, 3)
    assert spearman([1, 2, 2], [1, 2, 3]) == pytest.approx(0.8660254, abs=1e-6)
    assert spearman([1, 1, 1], [1, 2, 3]) is None


def test_true_scores_and_ranking_agreement() -> None:
    truth = {
        "a": {"x": "met", "y": "met"},
        "b": {"x": "met", "y": "not_met"},
        "c": {"x": "not_met", "y": "not_met"},
    }
    scores = true_scores(truth, {"x": 1.0, "y": 3.0})
    assert scores == {"a": 1.0, "b": 0.25, "c": 0.0}
    assert ranking_agreement(["a", "b", "c"], scores) == pytest.approx(1.0)
    assert ranking_agreement(["c", "b", "a"], scores) == pytest.approx(-1.0)
    # an unranked buyer shares the last position
    assert ranking_agreement(["a", "b"], scores) == pytest.approx(1.0)
