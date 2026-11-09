"""Bootstrap statistics of eval plan section 3.

Every per query metric is a `Sample` of numerator and denominator arrays: a mean of per query
values has denominator 1 per defined query, a ratio of counts (citation precision) has the
claim count as denominator. A resample is a vector of integer multiplicities over the units, so
the same `weights` matrix is applied to two systems (a paired bootstrap), and a cluster
bootstrap is the same machinery with multiplicities constant inside each cluster.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

DEFAULT_RESAMPLES = 2000
LEVEL = 0.95


@dataclass(frozen=True)
class Interval:
    estimate: float | None
    lo: float | None
    hi: float | None

    def contains(self, value: float) -> bool:
        return self.lo is not None and self.hi is not None and self.lo <= value <= self.hi


@dataclass(frozen=True)
class Sample:
    """One unit per query (or claim, or KPI cell). The metric is `sum(num) / sum(den)`."""

    num: FloatArray
    den: FloatArray

    @property
    def n_units(self) -> int:
        return len(self.num)

    def estimate(self) -> float | None:
        total = float(self.den.sum())
        return None if total == 0 else float(self.num.sum()) / total


def mean_sample(values: Sequence[float | None]) -> Sample:
    """Mean of per unit values, units without a value (`None`) are left out."""
    num = np.array([0.0 if v is None else v for v in values], dtype=np.float64)
    den = np.array([0.0 if v is None else 1.0 for v in values], dtype=np.float64)
    return Sample(num, den)


def count_sample(numerators: Sequence[float], denominators: Sequence[float]) -> Sample:
    return Sample(np.array(numerators, dtype=np.float64), np.array(denominators, dtype=np.float64))


def bootstrap_weights(
    n_units: int,
    *,
    seed: int,
    n_resamples: int = DEFAULT_RESAMPLES,
    clusters: Sequence[str] | None = None,
) -> FloatArray:
    """Multiplicities of shape `(n_resamples, n_units)`. With `clusters`, whole clusters are
    drawn with replacement and every unit of a drawn cluster is included."""
    if n_units == 0:
        return np.zeros((n_resamples, 0), dtype=np.float64)
    rng = np.random.default_rng(seed)
    if clusters is None:
        draws = rng.integers(0, n_units, size=(n_resamples, n_units))
        weights = np.zeros((n_resamples, n_units), dtype=np.float64)
        for row, drawn in enumerate(draws):
            weights[row] = np.bincount(drawn, minlength=n_units)
        return weights
    if len(clusters) != n_units:
        raise ValueError("one cluster label per unit is required")
    _, membership = np.unique(np.array(clusters), return_inverse=True)
    n_clusters = int(membership.max()) + 1 if n_units else 0
    draws = rng.integers(0, n_clusters, size=(n_resamples, n_clusters))
    counts = np.zeros((n_resamples, n_clusters), dtype=np.float64)
    for row, drawn in enumerate(draws):
        counts[row] = np.bincount(drawn, minlength=n_clusters)
    return counts[:, membership]


def resampled_values(sample: Sample, weights: FloatArray) -> FloatArray:
    """The metric on every resample; `nan` where the resampled denominator is zero."""
    num = weights @ sample.num
    den = weights @ sample.den
    out = np.full(num.shape, np.nan)
    np.divide(num, den, out=out, where=den > 0)
    return out


def _percentile_interval(values: FloatArray, estimate: float | None) -> Interval:
    finite = values[~np.isnan(values)]
    if len(finite) == 0:
        return Interval(estimate, None, None)
    tail = (1.0 - LEVEL) / 2.0 * 100.0
    lo, hi = np.percentile(finite, [tail, 100.0 - tail])
    return Interval(estimate, float(lo), float(hi))


def bootstrap_interval(sample: Sample, weights: FloatArray) -> Interval:
    """95 percent percentile interval of the metric."""
    return _percentile_interval(resampled_values(sample, weights), sample.estimate())


@dataclass(frozen=True)
class PairedComparison:
    a: Interval
    b: Interval
    diff: Interval  # a minus b
    share_positive: float | None  # share of resamples with a strictly larger than b
    share_tied: float | None
    p_value: float | None  # two sided, bootstrap, floored at 1 / (resamples + 1)


def paired_bootstrap(a: Sample, b: Sample, weights: FloatArray) -> PairedComparison:
    """Compare two systems on the SAME resamples of the same units."""
    if a.n_units != b.n_units:
        raise ValueError("paired samples need the same units")
    boot_a = resampled_values(a, weights)
    boot_b = resampled_values(b, weights)
    delta = boot_a - boot_b
    valid = delta[~np.isnan(delta)]
    est_a, est_b = a.estimate(), b.estimate()
    estimate = None if est_a is None or est_b is None else est_a - est_b
    if len(valid) == 0:
        return PairedComparison(
            _percentile_interval(boot_a, est_a),
            _percentile_interval(boot_b, est_b),
            Interval(estimate, None, None),
            None,
            None,
            None,
        )
    positive = float(np.mean(valid > 0))
    tied = float(np.mean(valid == 0))
    below = float(np.mean(valid <= 0))
    above = float(np.mean(valid >= 0))
    p_value = max(min(1.0, 2.0 * min(below, above)), 1.0 / (len(valid) + 1))
    return PairedComparison(
        a=_percentile_interval(boot_a, est_a),
        b=_percentile_interval(boot_b, est_b),
        diff=_percentile_interval(delta, estimate),
        share_positive=positive,
        share_tied=tied,
        p_value=p_value,
    )


def bootstrap_function(
    n_units: int,
    statistic: Callable[[IntArray], float | None],
    *,
    seed: int,
    n_resamples: int = DEFAULT_RESAMPLES,
) -> Interval:
    """Percentile interval for a statistic that is not a ratio of sums (a kappa, an F1).
    `statistic` receives the indices of one resample and the full index range for the estimate."""
    if n_units == 0:
        return Interval(None, None, None)
    rng = np.random.default_rng(seed)
    estimate = statistic(np.arange(n_units, dtype=np.int64))
    draws = rng.integers(0, n_units, size=(n_resamples, n_units))
    values = np.array(
        [np.nan if (v := statistic(row)) is None else v for row in draws], dtype=np.float64
    )
    return _percentile_interval(values, estimate)


def holm_adjust(p_values: Mapping[str, float]) -> dict[str, float]:
    """Holm step down adjusted p values for a declared family of comparisons."""
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - rank) * p))
        adjusted[name] = running
    return adjusted
