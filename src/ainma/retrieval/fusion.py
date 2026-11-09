"""Reciprocal rank fusion.

Ported as an idea from the legacy `search_document_chunks.py` (RRF over a vector and a keyword
list); new code, generalised to any number of rankings and per ranking weights:

    rrf(d) = sum over rankings i of w_i / (k + rank_i(d))      (rank starts at 1, k = 60)

A document absent from a ranking contributes nothing for that ranking.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence


def rrf_fuse[K: Hashable](
    rankings: Sequence[Sequence[K]], *, k: int = 60, weights: Sequence[float] | None = None
) -> dict[K, float]:
    if weights is None:
        weights = [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError("one weight per ranking is required")
    fused: dict[K, float] = {}
    for ranking, weight in zip(rankings, weights, strict=True):
        for rank, item in enumerate(ranking, start=1):
            fused[item] = fused.get(item, 0.0) + weight / (k + rank)
    return fused


def rrf_ceiling(*, k: int, weights: Sequence[float]) -> float:
    """Score of an item ranked first in every ranking: used to scale RRF into [0, 1]."""
    return sum(weights) / (k + 1)
