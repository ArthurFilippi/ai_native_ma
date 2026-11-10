"""Abstention and contradiction metrics on hand computed examples."""

from __future__ import annotations

import math

import pytest

from ainma.evaluation.metrics.abstention import (
    NO_EVIDENCE,
    abstention_rates,
    choose_tau,
    rates_at_tau,
    threshold_curve,
)
from ainma.evaluation.metrics.contradiction import contradiction_scores

ANSWERABLE = [0.9, 0.8, 0.4, 0.2]
UNANSWERABLE = [0.3, 0.1, 0.5]


def test_abstention_rates() -> None:
    # 2 of 3 unanswerable queries abstained: correct abstention 2/3.
    # 1 of 4 answerable queries abstained: false abstention 1/4.
    correct, false = abstention_rates([True, True, False], [True, False, False, False])
    assert correct == pytest.approx(2 / 3)
    assert false == pytest.approx(0.25)
    assert abstention_rates([], []) == (None, None)


def test_rates_at_tau_by_hand() -> None:
    # tau = 0.5, abstain when score < 0.5.
    # Answerable below: 0.4, 0.2 -> false abstention 2/4. Unanswerable below: 0.3, 0.1 -> 2/3.
    # Precision = unanswerable among all abstained = 2 / (2 + 2) = 0.5.
    point = rates_at_tau(0.5, ANSWERABLE, UNANSWERABLE)
    assert point.false_abstention_rate == pytest.approx(0.5)
    assert point.correct_abstention_rate == pytest.approx(2 / 3)
    assert point.precision == pytest.approx(0.5)


def test_missing_score_always_abstains() -> None:
    point = rates_at_tau(0.0, [None, 0.5], [None])
    assert point.false_abstention_rate == pytest.approx(0.5)
    assert point.correct_abstention_rate == pytest.approx(1.0)


def test_threshold_curve_by_hand() -> None:
    curve = {p.tau: p for p in threshold_curve(ANSWERABLE, UNANSWERABLE)}
    assert sorted(curve) == [0.1, 0.2, 0.3, 0.4, 0.5, 0.8, 0.9, math.inf]
    # tau = 0.1: nobody scores below it, so no abstention and no precision.
    assert curve[0.1].correct_abstention_rate == 0.0
    assert curve[0.1].precision is None
    # tau = 0.3: answerable below {0.2}, unanswerable below {0.1}: 1/4, 1/3, precision 1/2.
    assert curve[0.3].false_abstention_rate == pytest.approx(0.25)
    assert curve[0.3].correct_abstention_rate == pytest.approx(1 / 3)
    assert curve[0.3].precision == pytest.approx(0.5)
    # Above every score all 7 queries abstain: both rates are 1, precision is 3/7.
    assert curve[math.inf].false_abstention_rate == 1.0
    assert curve[math.inf].precision == pytest.approx(3 / 7)


def test_choose_tau_on_dev_by_hand() -> None:
    # Dev answerable scores sorted: 0.2, 0.4, 0.8, 0.9 (n = 4).
    # Target 0.25 allows m = 1 abstention: tau = 2nd smallest = 0.4, only 0.2 is below it.
    assert choose_tau(ANSWERABLE, 0.25) == pytest.approx(0.4)
    # Target 0.1 allows none: tau = smallest score, nobody is strictly below it.
    assert choose_tau(ANSWERABLE, 0.1) == pytest.approx(0.2)
    # A query without score is the lowest: with no allowance tau stays at "no threshold".
    assert choose_tau([None, 0.5], 0.0) == NO_EVIDENCE
    with pytest.raises(ValueError, match="target"):
        choose_tau(ANSWERABLE, 1.0)
    with pytest.raises(ValueError, match="no dev"):
        choose_tau([], 0.1)


def test_frozen_tau_false_abstention_stays_under_target_on_dev() -> None:
    tau = choose_tau(ANSWERABLE, 0.25)
    assert rates_at_tau(tau, ANSWERABLE, UNANSWERABLE).false_abstention_rate == pytest.approx(0.25)


def test_contradiction_scores_by_hand() -> None:
    # Planted pairs detected: T, T, F, F -> recall 2/4 = 0.5.
    # Controls flagged: T, F, F, F -> false positive rate 1/4.
    # Precision = TP / (TP + FP) = 2 / 3. F1 = 2TP / (2TP + FP + FN) = 4 / (4 + 1 + 2) = 4/7,
    # the harmonic mean of precision 2/3 and recall 1/2.
    scores = contradiction_scores([True, True, False, False], [True, False, False, False])
    assert scores.recall == pytest.approx(0.5)
    assert scores.false_positive_rate == pytest.approx(0.25)
    assert scores.precision == pytest.approx(2 / 3)
    assert scores.f1 == pytest.approx(4 / 7)


def test_contradiction_scores_without_detection() -> None:
    scores = contradiction_scores([False, False], [False])
    assert scores.recall == 0.0
    assert scores.precision is None
    assert scores.f1 == 0.0  # 2*0 / (0 + 0 + 2)
    assert contradiction_scores([], []).f1 is None
