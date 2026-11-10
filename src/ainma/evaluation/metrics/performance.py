"""Latency percentiles and cost per query (eval plan section 10)."""

from __future__ import annotations

from collections.abc import Sequence


def percentile(values: Sequence[float], q: float) -> float | None:
    """Percentile `q` in [0, 100] with linear interpolation between order statistics."""
    if not values:
        return None
    if not 0.0 <= q <= 100.0:
        raise ValueError("q must be in [0, 100]")
    ordered = sorted(values)
    rank = q / 100.0 * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (rank - low) * (ordered[high] - ordered[low])


def usd_cost(
    input_tokens: int,
    output_tokens: int,
    input_usd_per_million: float,
    output_usd_per_million: float,
) -> float:
    """Token usage times a price table entry (USD per million tokens)."""
    return (
        input_tokens * input_usd_per_million + output_tokens * output_usd_per_million
    ) / 1_000_000


def mean_cost(costs: Sequence[float | None]) -> float | None:
    """Mean cost per query, `None` when any query could not be priced (never a silent zero)."""
    if not costs or any(c is None for c in costs):
        return None
    return sum(c for c in costs if c is not None) / len(costs)
