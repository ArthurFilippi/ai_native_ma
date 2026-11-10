"""Okapi BM25, in house.

score(d, q) = sum over distinct query terms t of
    idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(d) / avg_len))
    idf(t) = ln(1 + (N - n_t + 0.5) / (n_t + 0.5))

Defaults k1 = 1.5 (term frequency saturation) and b = 0.75 (length normalisation). Queries are
deduplicated, so repeating a word does not count twice.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray


class BM25Index:
    def __init__(
        self, documents: Sequence[Sequence[str]], *, k1: float = 1.5, b: float = 0.75
    ) -> None:
        self._n = len(documents)
        self._k1 = k1
        self._b = b
        self._lengths = np.array([len(d) for d in documents], dtype=np.float64)
        self._avg_len = float(self._lengths.mean()) if self._n and self._lengths.sum() else 1.0
        self._postings: dict[str, list[tuple[int, int]]] = {}
        for index, document in enumerate(documents):
            for term, count in Counter(document).items():
                self._postings.setdefault(term, []).append((index, count))

    def idf(self, term: str) -> float:
        n_t = len(self._postings.get(term, ()))
        return math.log(1.0 + (self._n - n_t + 0.5) / (n_t + 0.5))

    def scores(self, query_terms: Sequence[str]) -> NDArray[np.float64]:
        result = np.zeros(self._n, dtype=np.float64)
        for term in dict.fromkeys(query_terms):
            idf = self.idf(term)
            for index, tf in self._postings.get(term, ()):
                norm = 1.0 - self._b + self._b * self._lengths[index] / self._avg_len
                result[index] += idf * tf * (self._k1 + 1.0) / (tf + self._k1 * norm)
        return result
