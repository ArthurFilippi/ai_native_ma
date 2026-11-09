"""Bootstrap statistics on known answer cases."""

from __future__ import annotations

import numpy as np
import pytest

from ainma.evaluation.stats import (
    bootstrap_function,
    bootstrap_interval,
    bootstrap_weights,
    count_sample,
    holm_adjust,
    mean_sample,
    paired_bootstrap,
)

VALUES = [0.1, 0.4, 0.9, 0.5, 0.7, 0.2, 0.8, 0.3, 0.6, 1.0, 0.0, 0.55]


def test_weights_are_multiplicities_and_reproducible() -> None:
    first = bootstrap_weights(12, seed=7, n_resamples=50)
    again = bootstrap_weights(12, seed=7, n_resamples=50)
    other = bootstrap_weights(12, seed=8, n_resamples=50)
    assert first.shape == (50, 12)
    assert (first.sum(axis=1) == 12).all()  # each resample draws n units
    assert np.array_equal(first, again)
    assert not np.array_equal(first, other)


def test_cluster_weights_are_constant_inside_a_cluster() -> None:
    clusters = ["d1", "d1", "d2", "d3", "d3", "d3"]
    weights = bootstrap_weights(6, seed=1, n_resamples=40, clusters=clusters)
    assert (weights[:, 0] == weights[:, 1]).all()
    assert (weights[:, 3] == weights[:, 4]).all()
    assert (weights[:, 4] == weights[:, 5]).all()
    with pytest.raises(ValueError, match="one cluster label"):
        bootstrap_weights(3, seed=1, clusters=["a"])


def test_interval_of_a_constant_is_that_constant() -> None:
    sample = mean_sample([0.5] * 10)
    interval = bootstrap_interval(sample, bootstrap_weights(10, seed=3, n_resamples=200))
    assert (interval.estimate, interval.lo, interval.hi) == (0.5, 0.5, 0.5)


def test_interval_brackets_the_mean() -> None:
    sample = mean_sample(VALUES)
    interval = bootstrap_interval(sample, bootstrap_weights(12, seed=5))
    assert interval.estimate == pytest.approx(sum(VALUES) / 12)
    assert interval.lo is not None and interval.hi is not None
    assert interval.lo < interval.estimate < interval.hi


def test_identical_systems_have_zero_differences() -> None:
    a = mean_sample(VALUES)
    result = paired_bootstrap(a, mean_sample(VALUES), bootstrap_weights(12, seed=5))
    assert result.diff.contains(0.0)
    assert (result.diff.lo, result.diff.hi) == (0.0, 0.0)
    assert result.share_positive == 0.0
    assert result.share_tied == 1.0
    assert result.p_value == 1.0


def test_a_constant_shift_excludes_zero() -> None:
    a = mean_sample([v + 0.1 for v in VALUES])
    b = mean_sample(VALUES)
    result = paired_bootstrap(a, b, bootstrap_weights(12, seed=5))
    assert result.diff.estimate == pytest.approx(0.1)
    assert result.diff.lo == pytest.approx(0.1)
    assert result.diff.hi == pytest.approx(0.1)
    assert not result.diff.contains(0.0)
    assert result.share_positive == 1.0
    assert result.p_value == pytest.approx(1 / 2001)


def test_the_same_resamples_are_used_for_both_systems() -> None:
    # If b were resampled differently the interval of a - b would be wider than the interval of
    # the per unit differences resampled once. With shared weights they must agree exactly.
    rng = np.random.default_rng(0)
    base = rng.random(30).tolist()
    noise = (rng.random(30) * 0.1).tolist()
    a = mean_sample([x + y for x, y in zip(base, noise, strict=True)])
    b = mean_sample(base)
    weights = bootstrap_weights(30, seed=11)
    paired = paired_bootstrap(a, b, weights)
    direct = bootstrap_interval(mean_sample(noise), weights)
    assert paired.diff.lo == pytest.approx(direct.lo)
    assert paired.diff.hi == pytest.approx(direct.hi)


def test_fixed_seed_reproduces_the_same_interval() -> None:
    sample = mean_sample(VALUES)
    one = bootstrap_interval(sample, bootstrap_weights(12, seed=42))
    two = bootstrap_interval(sample, bootstrap_weights(12, seed=42))
    assert one == two


def test_ratio_sample_by_hand() -> None:
    # Citation precision as a ratio of sums: 3 correct of 4 claims in query 1, 0 of 1 in
    # query 2 is 3/5, not the mean of 3/4 and 0.
    sample = count_sample([3, 0], [4, 1])
    assert sample.estimate() == pytest.approx(0.6)


def test_units_without_denominator_are_ignored() -> None:
    sample = mean_sample([1.0, None, 0.0])
    assert sample.estimate() == pytest.approx(0.5)


def test_cluster_bootstrap_is_wider_for_correlated_units() -> None:
    # Two clusters whose units are identical inside: the cluster bootstrap sees two effective
    # observations, the plain bootstrap sees twenty.
    values = [0.0] * 10 + [1.0] * 10
    clusters = ["a"] * 10 + ["b"] * 10
    sample = mean_sample(values)
    plain = bootstrap_interval(sample, bootstrap_weights(20, seed=2))
    clustered = bootstrap_interval(sample, bootstrap_weights(20, seed=2, clusters=clusters))
    assert plain.lo is not None and plain.hi is not None
    assert clustered.lo is not None and clustered.hi is not None
    assert clustered.hi - clustered.lo > plain.hi - plain.lo
    assert (clustered.lo, clustered.hi) == (0.0, 1.0)


def test_bootstrap_function_for_a_non_linear_statistic() -> None:
    data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

    def median(idx: np.ndarray) -> float:
        return float(np.median(data[idx]))

    interval = bootstrap_function(5, median, seed=1, n_resamples=300)
    assert interval.estimate == 3.0
    assert interval.lo is not None and interval.hi is not None
    assert 1.0 <= interval.lo <= 3.0 <= interval.hi <= 5.0


def test_holm_by_hand() -> None:
    # p = 0.01, 0.04, 0.03 sorted 0.01, 0.03, 0.04 with m = 3:
    # 0.01 * 3 = 0.03; 0.03 * 2 = 0.06; 0.04 * 1 = 0.04 -> raised to 0.06 by monotonicity.
    adjusted = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adjusted == {
        "a": pytest.approx(0.03),
        "c": pytest.approx(0.06),
        "b": pytest.approx(0.06),
    }
    assert holm_adjust({"x": 0.9}) == {"x": 0.9}
