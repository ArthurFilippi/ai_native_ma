"""Small shared helpers. A rate over an empty denominator is `None` (not applicable), never 0."""

from __future__ import annotations

from collections.abc import Sequence


def share(flags: Sequence[bool]) -> float | None:
    """Share of `True` in `flags`, or `None` when `flags` is empty."""
    if not flags:
        return None
    return sum(1 for flag in flags if flag) / len(flags)


def ratio(numerator: float, denominator: float) -> float | None:
    """`numerator / denominator`, or `None` when the denominator is zero."""
    if denominator == 0:
        return None
    return numerator / denominator


def mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
