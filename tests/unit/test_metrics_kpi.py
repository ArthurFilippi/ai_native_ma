"""KPI, screening, agreement and performance metrics on hand computed examples."""

from __future__ import annotations

import pytest

from ainma.evaluation.metrics.agreement import (
    cohen_kappa,
    confusion_matrix,
    weighted_kappa,
)
from ainma.evaluation.metrics.kpi import (
    KpiOutcome,
    kpi_scores,
    quote_contains_value,
    within_tolerance,
)
from ainma.evaluation.metrics.performance import mean_cost, percentile, usd_cost
from ainma.evaluation.metrics.screening import screening_scores


def test_within_tolerance() -> None:
    assert within_tolerance(100.4, 100.0)  # 0.4 percent off
    assert not within_tolerance(100.6, 100.0)  # 0.6 percent off
    assert within_tolerance(0.0, 0.0)
    assert not within_tolerance(0.01, 0.0)


def test_kpi_scores_by_hand() -> None:
    # Truth cells: 100, 200, 50, 10. Extracted: 100.4 (right), 203 (1.5 percent off: wrong),
    # None (missing), 10 (right).
    # Accuracy 2/4. Wrong value rate 1 of 3 non missing. Missing rate 1/4.
    # Citation validity over the two sourced values: one valid, one invalid = 1/2.
    outcomes = [
        KpiOutcome(100.0, 100.4, True),
        KpiOutcome(200.0, 203.0, None),
        KpiOutcome(50.0, None, None),
        KpiOutcome(10.0, 10.0, False),
    ]
    scores = kpi_scores(outcomes)
    assert scores.accuracy == pytest.approx(0.5)
    assert scores.wrong_value_rate == pytest.approx(1 / 3)
    assert scores.missing_rate == pytest.approx(0.25)
    assert scores.citation_validity == pytest.approx(0.5)


def test_kpi_scores_with_everything_missing() -> None:
    scores = kpi_scores([KpiOutcome(1.0, None), KpiOutcome(2.0, None)])
    assert scores.accuracy == 0.0
    assert scores.wrong_value_rate is None
    assert scores.missing_rate == 1.0
    assert scores.citation_validity is None


def test_quote_contains_value_accepts_scale_changes() -> None:
    assert quote_contains_value("Net revenue reached EUR 182.4 million", 182.4)
    assert quote_contains_value("Net revenue reached EUR 182,400 thousand", 182.4)
    assert not quote_contains_value("Net revenue reached EUR 179 million", 182.4)


def test_screening_scores_by_hand() -> None:
    # (truth, predicted): (met, met) (not_met, met) (met, unknown) (not_met, not_met) (unk, unk)
    # Agreement 3/5. Unknown rate 2/5. Known predictions 3, two correct: 2/3.
    # Predicted met twice, once wrongly: false met rate 1/2.
    pairs = [
        ("met", "met"),
        ("not_met", "met"),
        ("met", "unknown"),
        ("not_met", "not_met"),
        ("unknown", "unknown"),
    ]
    scores = screening_scores(pairs)
    assert scores.agreement == pytest.approx(0.6)
    assert scores.unknown_rate == pytest.approx(0.4)
    assert scores.accuracy_known == pytest.approx(2 / 3)
    assert scores.false_met_rate == pytest.approx(0.5)


def test_cohen_kappa_by_hand() -> None:
    # Binary example on labels (supported, unsupported). a = S S U U, b = S U U U.
    # p_o = 3/4. a marginal P(S) = 1/2, b marginal P(S) = 1/4:
    # p_e = 1/2 * 1/4 + 1/2 * 3/4 = 1/2. kappa = (3/4 - 1/2) / (1 - 1/2) = 0.5.
    a = ["supported", "supported", "unsupported", "unsupported"]
    b = ["supported", "unsupported", "unsupported", "unsupported"]
    assert cohen_kappa(a, b, ("supported", "unsupported")) == pytest.approx(0.5)
    assert cohen_kappa(a, a, ("supported", "unsupported")) == pytest.approx(1.0)


def test_kappa_is_undefined_with_a_single_label() -> None:
    assert cohen_kappa(["supported"] * 3, ["supported"] * 3) is None


def test_weighted_kappa_by_hand() -> None:
    # Ordered labels 0 < 1 < 2. a = 0 1 2 2, b = 0 2 2 1, n = 4. Linear weights |i - j| / 2.
    # Observed disagreement: (0 + 0.5 + 0 + 0.5) / 4 = 0.25.
    # Both marginals are (1/4, 1/4, 1/2). Expected disagreement:
    #   2 * (1/4*1/4*0.5) + 2 * (1/4*1/2*1) + 2 * (1/4*1/2*0.5) = 0.0625 + 0.25 + 0.125 = 0.4375.
    # kappa_w = 1 - 0.25 / 0.4375 = 3/7.
    labels = ("supported", "partial", "unsupported")
    a = ["supported", "partial", "unsupported", "unsupported"]
    b = ["supported", "unsupported", "unsupported", "partial"]
    assert weighted_kappa(a, b, labels) == pytest.approx(3 / 7)
    # The unweighted kappa of the same data: p_o = 2/4; p_e = 1/16 + 1/16 + 1/4 = 3/8;
    # kappa = (1/2 - 3/8) / (5/8) = 0.2.
    assert cohen_kappa(a, b, labels) == pytest.approx(0.2)


def test_confusion_matrix() -> None:
    labels = ("supported", "partial", "unsupported")
    reference = ["supported", "partial", "unsupported", "unsupported"]
    predicted = ["supported", "unsupported", "unsupported", "partial"]
    assert confusion_matrix(reference, predicted, labels) == [[1, 0, 0], [0, 0, 1], [0, 1, 1]]


def test_percentile_by_hand() -> None:
    # Sorted 10 20 30 40: rank for p50 is 0.5 * 3 = 1.5, so 20 + 0.5 * 10 = 25.
    # p95: rank 2.85, so 30 + 0.85 * 10 = 38.5.
    values = [40.0, 10.0, 30.0, 20.0]
    assert percentile(values, 50) == pytest.approx(25.0)
    assert percentile(values, 95) == pytest.approx(38.5)
    assert percentile(values, 0) == 10.0
    assert percentile(values, 100) == 40.0
    assert percentile([], 50) is None
    with pytest.raises(ValueError, match="q must"):
        percentile(values, 101)


def test_cost_per_query() -> None:
    # 1000 input tokens at 0.5 USD per million plus 500 output tokens at 1.5 USD per million:
    # 0.0005 + 0.00075 = 0.00125.
    assert usd_cost(1000, 500, 0.5, 1.5) == pytest.approx(0.00125)
    assert mean_cost([0.001, 0.003]) == pytest.approx(0.002)
    assert mean_cost([0.001, None]) is None
    assert mean_cost([]) is None
