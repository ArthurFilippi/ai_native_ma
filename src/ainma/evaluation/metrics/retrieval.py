"""Retrieval metrics of eval plan section 3, for graded judgments `rel in {0, 1, 2}`."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def dcg_at_k(rels: Sequence[int], k: int) -> float:
    """`DCG@k = sum_{i=1..k} (2^rel_i - 1) / log2(i + 1)` over the ranked relevance grades."""
    return sum(((1 << rel) - 1) / math.log2(i + 1) for i, rel in enumerate(rels[:k], start=1))


def ndcg_at_k(ranked_ids: Sequence[str], relevance: Mapping[str, int], k: int) -> float | None:
    """`DCG@k / IDCG@k`. Unjudged chunks count as 0. `None` when nothing is relevant."""
    ideal = sorted(relevance.values(), reverse=True)
    idcg = dcg_at_k(ideal, k)
    if idcg == 0:
        return None
    return dcg_at_k([relevance.get(chunk_id, 0) for chunk_id in ranked_ids], k) / idcg


def recall_at_k(ranked_ids: Sequence[str], relevance: Mapping[str, int], k: int) -> float | None:
    """Relevant (`rel >= 1`) chunks in the top k over all relevant chunks."""
    relevant = {chunk_id for chunk_id, rel in relevance.items() if rel >= 1}
    if not relevant:
        return None
    return len(relevant.intersection(ranked_ids[:k])) / len(relevant)


def reciprocal_rank(ranked_ids: Sequence[str], relevance: Mapping[str, int]) -> float | None:
    """`1 / rank` of the first chunk with `rel = 2`; 0 when none is retrieved, `None` when the
    query has no `rel = 2` chunk."""
    if not any(rel == 2 for rel in relevance.values()):
        return None
    for rank, chunk_id in enumerate(ranked_ids, start=1):
        if relevance.get(chunk_id, 0) == 2:
            return 1.0 / rank
    return 0.0
