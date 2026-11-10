"""Retrieval metrics on a three document list worked out by hand."""

from __future__ import annotations

import math

import pytest

from ainma.evaluation.metrics.retrieval import (
    dcg_at_k,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)

# Judgments: a has grade 2, b has grade 1, c and x are unjudged (grade 0).
RELEVANCE = {"a": 2, "b": 1}
RANKED = ["b", "x", "a"]


def test_dcg_by_hand() -> None:
    # Grades in rank order: 1, 0, 2.
    # DCG@3 = (2^1 - 1)/log2(2) + (2^0 - 1)/log2(3) + (2^2 - 1)/log2(4) = 1 + 0 + 3/2 = 2.5
    assert dcg_at_k([1, 0, 2], 3) == pytest.approx(2.5)
    # DCG@1 only counts the first rank: 1/log2(2) = 1.
    assert dcg_at_k([1, 0, 2], 1) == pytest.approx(1.0)


def test_ndcg_by_hand() -> None:
    # Ideal order is a (2), b (1): IDCG@3 = 3/log2(2) + 1/log2(3) = 3 + 0.6309298 = 3.6309298.
    # nDCG@3 = 2.5 / 3.6309298 = 0.6885...
    expected = 2.5 / (3 + 1 / math.log2(3))
    assert ndcg_at_k(RANKED, RELEVANCE, 3) == pytest.approx(expected)
    assert expected == pytest.approx(0.68853, abs=1e-4)
    # A perfect ranking scores exactly 1.
    assert ndcg_at_k(["a", "b", "x"], RELEVANCE, 3) == pytest.approx(1.0)


def test_ndcg_is_undefined_without_relevant_chunks() -> None:
    assert ndcg_at_k(["a"], {}, 10) is None
    assert ndcg_at_k(["a"], {"a": 0}, 10) is None


def test_recall_by_hand() -> None:
    # Relevant set is {a, b}. Ranking b, x, a: top 1 and top 2 hold one of two, top 3 both.
    assert recall_at_k(RANKED, RELEVANCE, 1) == pytest.approx(0.5)
    assert recall_at_k(RANKED, RELEVANCE, 2) == pytest.approx(0.5)
    assert recall_at_k(RANKED, RELEVANCE, 3) == pytest.approx(1.0)
    assert recall_at_k(RANKED, {}, 3) is None


def test_reciprocal_rank_by_hand() -> None:
    # The first grade 2 chunk is a at rank 3, so 1/3. b (grade 1) does not count.
    assert reciprocal_rank(RANKED, RELEVANCE) == pytest.approx(1 / 3)
    assert reciprocal_rank(["x", "y"], RELEVANCE) == 0.0
    assert reciprocal_rank(RANKED, {"b": 1}) is None
