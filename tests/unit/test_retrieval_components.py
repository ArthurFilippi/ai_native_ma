"""Hand computable checks of BM25, RRF, the reranker features and the source ranker formula."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest

from ainma.contracts import Chunk, DocType, DocumentMeta
from ainma.retrieval.bm25 import BM25Index
from ainma.retrieval.config import RankerConfig, RerankerWeights
from ainma.retrieval.embedder import FastEmbedEmbedder, LsaEmbedder
from ainma.retrieval.fusion import rrf_ceiling, rrf_fuse
from ainma.retrieval.quantities import extract_facts_rules
from ainma.retrieval.ranker import (
    corroboration_bonus,
    corroboration_count,
    final_score,
    independent,
    recency_factor,
)
from ainma.retrieval.rerank import CrossEncoderReranker, FeatureReranker


def test_bm25_three_documents_by_hand() -> None:
    docs = [["a", "b"], ["a", "a", "c"], ["d"]]
    index = BM25Index(docs, k1=1.5, b=0.75)
    idf_a = math.log(1 + (3 - 2 + 0.5) / (2 + 0.5))  # ln 1.6
    assert index.idf("a") == pytest.approx(idf_a)
    assert index.idf("zzz") == pytest.approx(math.log(1 + 3.5 / 0.5))
    avg = (2 + 3 + 1) / 3
    s0 = idf_a * 1 * 2.5 / (1 + 1.5 * (0.25 + 0.75 * 2 / avg))
    s1 = idf_a * 2 * 2.5 / (2 + 1.5 * (0.25 + 0.75 * 3 / avg))
    scores = index.scores(["a"])
    assert scores == pytest.approx([s0, s1, 0.0])
    assert s0 == pytest.approx(0.470 * 1.0, abs=1e-3) and s1 == pytest.approx(0.5785, abs=1e-3)
    assert index.scores(["a", "a"]).tolist() == scores.tolist()  # repeated terms count once
    assert index.scores(["unknown"]).tolist() == [0.0, 0.0, 0.0]


def test_rrf_by_hand() -> None:
    fused = rrf_fuse([["x", "y", "z"], ["y", "x"]], k=60)
    assert fused["x"] == pytest.approx(1 / 61 + 1 / 62)
    assert fused["y"] == pytest.approx(1 / 62 + 1 / 61)
    assert fused["z"] == pytest.approx(1 / 63)
    weighted = rrf_fuse([["x"], ["y"]], k=60, weights=[2.0, 1.0])
    assert weighted == {"x": pytest.approx(2 / 61), "y": pytest.approx(1 / 61)}
    assert rrf_ceiling(k=60, weights=[1.0, 1.0]) == pytest.approx(2 / 61)
    with pytest.raises(ValueError):
        rrf_fuse([["x"]], weights=[1.0, 2.0])


def test_reranker_features_by_hand() -> None:
    reranker = FeatureReranker()
    query = "FY2024 revenue EUR 182.4 million"
    good = "Net revenue for FY2024 reached EUR 182.4 million."
    other_period = "Net revenue for FY2023 reached EUR 168.0 million."
    unrelated = "The playbook describes bidder communication."
    f = reranker.features(query, good)
    assert f["metric"] == 1.0 and f["period"] == 1.0 and f["numbers"] == 1.0
    assert f["coverage"] == 1.0
    g = reranker.features(query, other_period)
    assert g["period"] == 0.0 and g["numbers"] == 0.0 and g["metric"] == 1.0
    assert reranker.features(query, "revenue was strong")["period"] == 0.3
    # no number, no period, no metric in the query: those features are inactive
    h = reranker.features("bidder communication", unrelated)
    assert h["numbers"] is None and h["period"] is None and h["metric"] is None
    scores = reranker.score(query, [good, other_period, unrelated])
    assert scores[0] > scores[1] > scores[2]
    # the metric and period words are judged by their own features: the residual query is
    # "EUR 182.4 million", whose two adjacent pairs are both in the passage
    assert f["phrase"] == pytest.approx(1.0)
    assert f["fact"] == 1.0  # the passage states revenue for FY2024 as a number
    assert scores[0] == pytest.approx(0.25 + 0.10 * 1.0 + 0.15 + 0.10 + 0.15 + 0.25)
    share = reranker.features("FY2024 revenue", "17 percent of FY2024 revenue.")
    assert share["metric"] == 1.0 and share["fact"] == 0.0  # same keywords, not a revenue figure
    # weighted mean of the active features, by hand, for the second passage
    w = RerankerWeights()
    f2 = reranker.features(query, other_period)
    active = {k: v for k, v in f2.items() if v is not None}
    expected = sum(getattr(w, k) * v for k, v in active.items()) / sum(
        getattr(w, k) for k in active
    )
    assert scores[1] == pytest.approx(expected)


def _doc(doc_id: str, sha: str, superseded_by: str | None = None) -> DocumentMeta:
    return DocumentMeta(
        id=doc_id,
        title=doc_id,
        doc_type=DocType.PRESS_ARTICLE,
        n_pages=1,
        sha256=sha,
        superseded_by=superseded_by,
    )


def test_source_ranker_formula_by_hand() -> None:
    config = RankerConfig()
    # press article (tier 4, weight 0.45, half life 120 d), 60 days old: 0.5 ** 0.5
    recency = recency_factor(date(2025, 1, 1), 120.0, date(2025, 3, 2), 0.5)
    assert recency == pytest.approx(0.5**0.5)
    score = final_score(relevance=0.9, tier_weight=0.45, recency=recency, status=1.0, bonus=0.05)
    assert score == pytest.approx(0.9 * 0.45 * 0.5**0.5 + 0.05)
    assert final_score(relevance=0.9, tier_weight=1.0, recency=1.0, status=0.0, bonus=0.15) == 0.0
    assert final_score(relevance=0.9, tier_weight=1.0, recency=1.0, status=0.2, bonus=0.0) == (
        pytest.approx(0.18)
    )
    assert final_score(relevance=1.0, tier_weight=1.0, recency=1.0, status=1.0, bonus=0.15) == 1.0
    assert recency_factor(None, 120.0, date(2025, 1, 1), 0.5) == 0.5
    assert recency_factor(date(2026, 1, 1), 120.0, date(2025, 1, 1), 0.5) == 1.0  # future date
    assert [corroboration_bonus(n, config) for n in (0, 1, 3, 9)] == pytest.approx(
        [0.0, 0.05, 0.15, 0.15]
    )


def test_independence_and_corroboration_count() -> None:
    a, b, c = _doc("a", "s1"), _doc("b", "s2"), _doc("c", "s3", superseded_by="a")
    assert independent(a, b)
    assert not independent(a, a)
    assert not independent(a, _doc("copy", "s1"))  # identical content
    assert not independent(a, c) and not independent(c, a)  # linked by superseded_by
    fact = extract_facts_rules("Revenue for FY2024 was EUR 182.4 million.")
    near = extract_facts_rules("Revenue for FY2024 was EUR 182.5 million.")  # within 0.5 percent
    far = extract_facts_rules("Revenue for FY2024 was EUR 179 million.")
    others = [(b, near), (c, fact), (_doc("d", "s4"), far)]
    assert corroboration_count(a, fact, others, 0.005) == 1  # b only: c is linked, d disagrees


def test_lsa_embedder_is_deterministic_and_normalised() -> None:
    texts = [
        "revenue grew strongly in the year",
        "gross margin improved in the year",
        "the playbook describes bidder communication",
        "customer concentration is moderate",
        "bidder communication follows one channel",
    ]
    first, second = LsaEmbedder(dim=3, seed=1), LsaEmbedder(dim=3, seed=1)
    first.fit(texts)
    second.fit(texts)
    vectors = first.embed(texts)
    assert np.allclose(vectors, second.embed(texts))
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert np.allclose(first.embed(["zzzz qqqq"]), 0.0)  # out of vocabulary: zero vector
    query = first.embed(["bidder communication"])[0]
    sims = vectors @ query
    assert sims[2] > sims[0] and sims[4] > sims[1]


def test_lsa_on_a_single_text_falls_back_to_tfidf() -> None:
    embedder = LsaEmbedder()
    embedder.fit(["only one text here"])
    assert embedder.embed(["only text"])[0].sum() > 0


def test_optional_backends_fail_with_a_clear_message_when_absent() -> None:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError, match="local-models"):
            FastEmbedEmbedder()
        with pytest.raises(ImportError, match="local-models"):
            CrossEncoderReranker()
    else:  # pragma: no cover: only on machines with the optional extra
        assert FastEmbedEmbedder.__name__ == "FastEmbedEmbedder"


def test_chunk_type_is_exported() -> None:
    assert Chunk.__name__ == "Chunk"
