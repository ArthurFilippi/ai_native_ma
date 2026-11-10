"""Rerankers behind the `Reranker` protocol of spec section 4.

`FeatureReranker` (offline default) scores a passage in [0, 1] from five features of the query
and the passage, then takes the weighted mean of the features that apply to the query:

- coverage: share of distinct query terms (stemmed, stop words removed) found in the passage;
- phrase: share of adjacent query term pairs found adjacent in the passage;
- numbers: share of the query's numbers (years excluded) found in the passage, unit and scale
  normalised;
- metric: share of the query's metrics (revenue, gross margin, ...) the passage mentions;
- period: 1 when a query period appears, 0 when the passage only mentions other periods, and
  `period_unmentioned` when it mentions none;
- fact: share of the query's (metric, period) pairs for which the passage states a number, found
  by the rule based fact extractor. It separates "revenue was EUR 182.4 million" from "17 percent
  of revenue", which share every keyword.

`CrossEncoderReranker` wraps a pretrained cross encoder through `fastembed` (lazy import) and
squashes its logits with a sigmoid so scores stay in [0, 1].
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

from ainma.retrieval.config import RerankerWeights
from ainma.retrieval.lexicon import detect_metrics, detect_periods
from ainma.retrieval.quantities import (
    ExtractedFact,
    extract_facts_rules,
    parse_quantities,
    quantities_match,
)
from ainma.retrieval.text import tokenize


class Reranker(Protocol):
    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


class FeatureReranker:
    def __init__(self, weights: RerankerWeights | None = None) -> None:
        self._weights = weights or RerankerWeights()

    def features(self, query: str, passage: str) -> dict[str, float | None]:
        """Each feature in [0, 1], or None when it does not apply to this query."""
        q_tokens = tokenize(query)
        p_tokens = tokenize(passage)
        q_terms, p_terms = set(q_tokens), set(p_tokens)
        coverage = len(q_terms & p_terms) / len(q_terms) if q_terms else None

        q_pairs = set(zip(q_tokens, q_tokens[1:], strict=False))
        p_pairs = set(zip(p_tokens, p_tokens[1:], strict=False))
        phrase = len(q_pairs & p_pairs) / len(q_pairs) if q_pairs else None

        q_numbers = [q for q in parse_quantities(query) if q.kind != "year"]
        p_numbers = parse_quantities(passage)
        numbers = (
            sum(any(quantities_match(q, p) for p in p_numbers) for q in q_numbers) / len(q_numbers)
            if q_numbers
            else None
        )

        q_metrics = detect_metrics(query)
        p_metrics = set(detect_metrics(passage))
        metric = sum(m in p_metrics for m in q_metrics) / len(q_metrics) if q_metrics else None

        q_periods = detect_periods(query)
        p_periods = set(detect_periods(passage))
        period: float | None = None
        if q_periods:
            if p_periods & set(q_periods):
                period = 1.0
            elif p_periods:
                period = 0.0
            else:
                period = self._weights.period_unmentioned
        fact: float | None = None
        if q_metrics:
            facts = extract_facts_rules(passage)
            periods_or_any: list[str | None] = list(q_periods) if q_periods else [None]
            pairs = [(m, p) for m in q_metrics for p in periods_or_any]
            fact = sum(self._fact_credit(facts, m, p) for m, p in pairs) / len(pairs)
        return {
            "fact": fact,
            "coverage": coverage,
            "phrase": phrase,
            "numbers": numbers,
            "metric": metric,
            "period": period,
        }

    def _fact_credit(self, facts: list[ExtractedFact], metric: str, period: str | None) -> float:
        credit = 0.0
        for fact in facts:
            if fact.metric != metric:
                continue
            if period is None or fact.period == period:
                return 1.0
            if fact.period is None:
                credit = max(credit, self._weights.fact_undated)
        return credit

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        weights = self._weights.model_dump()
        scores: list[float] = []
        for passage in passages:
            total = weight_sum = 0.0
            for name, value in self.features(query, passage).items():
                if value is not None:
                    total += weights[name] * value
                    weight_sum += weights[name]
            scores.append(total / weight_sum if weight_sum else 0.0)
        return scores


class CrossEncoderReranker:
    def __init__(self, model_name: str = "Xenova/ms-marco-MiniLM-L-6-v2") -> None:
        try:
            from fastembed.rerank.cross_encoder import (  # type: ignore[import-not-found,unused-ignore]
                TextCrossEncoder,
            )
        except ImportError as error:
            raise ImportError(
                "the cross encoder needs the optional extra: pip install 'ainma[local-models]'"
            ) from error
        self._model = TextCrossEncoder(model_name=model_name)

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        logits = list(self._model.rerank(query, list(passages)))
        return [1.0 / (1.0 + math.exp(-float(x))) for x in logits]
