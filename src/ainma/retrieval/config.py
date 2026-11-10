"""All retrieval and ranking constants in one object, so the ablations can sweep them."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ainma.contracts import TIER_WEIGHT, DocStatus, DocType, SourceTier
from ainma.settings import DEFAULT_SEED

System = Literal["A1", "A2", "A3", "A4", "A5"]
"""A1 BM25, A2 dense, A3 RRF, A4 RRF plus reranker, A5 A4 plus the source ranker."""


class RerankerWeights(BaseModel):
    """Weights of the feature based reranker. Inactive features (the query has no number, no
    period, no metric) are left out and the others are renormalised."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    coverage: float = 0.25  # share of distinct query terms present in the passage
    phrase: float = 0.10  # share of adjacent query term pairs present in the passage
    numbers: float = 0.15  # share of query numbers present in the passage
    metric: float = 0.10  # share of query metrics (revenue, gross margin) mentioned
    period: float = 0.15  # 1 period match, 0 only other periods, `period_unmentioned` otherwise
    fact: float = 0.25  # share of (metric, period) pairs the passage states as a number
    entity_floor: float = 0.1  # score kept by a passage whose document does not name the entity
    period_unmentioned: float = 0.30
    fact_undated: float = 0.5  # credit for a number of the right metric with no period


class RankerConfig(BaseModel):
    """Source ranker of spec section 7: tier, recency, status, corroboration, staleness."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tier_weights: dict[SourceTier, float] = Field(default_factory=lambda: dict(TIER_WEIGHT))
    half_life_days: dict[DocType, float] = Field(
        default_factory=lambda: {
            DocType.SIGNED_AGREEMENT: 1460.0,
            DocType.REGULATORY_FILING: 730.0,
            DocType.DEAL_DOCUMENT: 365.0,
            DocType.COMPANY_REPORT: 730.0,
            DocType.INTERNAL_REFERENCE: 1095.0,
            DocType.PRESS_RELEASE: 120.0,
            DocType.PRESS_ARTICLE: 120.0,
            DocType.WEB: 120.0,
        }
    )
    stale_days: dict[DocType, int] = Field(
        default_factory=lambda: {
            DocType.SIGNED_AGREEMENT: 730,
            DocType.REGULATORY_FILING: 730,
            DocType.DEAL_DOCUMENT: 540,
            DocType.COMPANY_REPORT: 730,
            DocType.INTERNAL_REFERENCE: 1095,
            DocType.PRESS_RELEASE: 180,
            DocType.PRESS_ARTICLE: 180,
            DocType.WEB: 180,
        }
    )
    status_factors: dict[DocStatus, float] = Field(
        default_factory=lambda: {
            DocStatus.CURRENT: 1.0,
            DocStatus.SUPERSEDED: 0.2,
            DocStatus.WITHDRAWN: 0.0,
        }
    )
    trust_exponent: float = 0.1  # final = relevance * (tier * recency) ** exponent * status
    out_of_scope_weight: float = 0.7  # general layer passages not named by a deal question
    undated_recency: float = 0.5
    corroboration_step: float = 0.05
    corroboration_cap: int = 3
    corroboration_tolerance: float = 0.005


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    system: System = "A5"
    rrf_k: int = 60
    rrf_weights: tuple[float, float] = (1.0, 1.0)  # (bm25, dense)
    rerank_top: int = 30
    entity_expansion: int = 40  # extra chunks of documents naming the asked entity (0: off)
    top_k: int = 10
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    bm25_scale: float = 10.0  # relevance of A1 is bm25 / (bm25 + bm25_scale), in [0, 1)
    embedder: Literal["lsa", "fastembed"] = "lsa"
    embedder_model: str = "BAAI/bge-small-en-v1.5"
    lsa_dim: int = 128
    concept_tokens: bool = True  # BM25 and LSA also read one token per metric a text states
    seed: int = DEFAULT_SEED
    reranker: Literal["features", "cross_encoder"] = "features"
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_weight: float = 0.8  # relevance = w * rerank + (1 - w) * rrf_norm (A4 and A5)
    reranker_weights: RerankerWeights = Field(default_factory=RerankerWeights)
    ranker: RankerConfig = Field(default_factory=RankerConfig)
    as_of: date | None = None  # None: the newest publication date in the candidate set
