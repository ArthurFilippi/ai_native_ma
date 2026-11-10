"""Embedders behind the `Embedder` protocol of spec section 4.

The offline default is LSA: TF-IDF (sublinear tf, our tokenizer) reduced by a truncated SVD and
L2 normalised. It is fitted on the candidate set only, so nothing outside the access scope can
influence a vector. `FastEmbedEmbedder` wraps a pretrained model and imports `fastembed` lazily
(optional extra `local-models`).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from sklearn.decomposition import TruncatedSVD  # type: ignore[import-untyped]
from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore[import-untyped]

from ainma.retrieval.text import tokenize


class Embedder(Protocol):
    name: str

    def fit(self, texts: Sequence[str]) -> None: ...

    def embed(self, texts: Sequence[str]) -> NDArray[np.float64]: ...


def _normalise(matrix: NDArray[np.float64]) -> NDArray[np.float64]:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    out: NDArray[np.float64] = matrix / norms
    return out


class LsaEmbedder:
    name = "lsa"

    def __init__(self, dim: int = 128, seed: int = 1234) -> None:
        self._dim = dim
        self._seed = seed
        self._vectorizer: TfidfVectorizer | None = None
        self._svd: TruncatedSVD | None = None

    def fit(self, texts: Sequence[str]) -> None:
        vectorizer = TfidfVectorizer(
            tokenizer=tokenize, lowercase=False, token_pattern=None, sublinear_tf=True
        )
        try:
            tfidf = vectorizer.fit_transform(texts)
        except ValueError:  # empty vocabulary: every embedding will be the zero vector
            self._vectorizer, self._svd = None, None
            return
        self._vectorizer = vectorizer
        components = min(self._dim, tfidf.shape[1] - 1, tfidf.shape[0] - 1)
        if components >= 2:
            self._svd = TruncatedSVD(n_components=components, random_state=self._seed)
            self._svd.fit(tfidf)
        else:  # too small for a decomposition: plain TF-IDF cosine
            self._svd = None

    def embed(self, texts: Sequence[str]) -> NDArray[np.float64]:
        if self._vectorizer is None:
            return np.zeros((len(texts), 1), dtype=np.float64)
        tfidf = self._vectorizer.transform(texts)
        if self._svd is None:
            dense = np.asarray(tfidf.todense(), dtype=np.float64)
        else:
            dense = np.asarray(self._svd.transform(tfidf), dtype=np.float64)
        return _normalise(dense)


class FastEmbedEmbedder:
    """Pretrained local model through `fastembed`; `fit` is a no-op."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        try:
            from fastembed import TextEmbedding  # type: ignore[import-not-found,unused-ignore]
        except ImportError as error:
            raise ImportError(
                "the fastembed backend needs the optional extra: pip install 'ainma[local-models]'"
            ) from error
        self.name = f"fastembed:{model_name}"
        self._model = TextEmbedding(model_name=model_name)

    def fit(self, texts: Sequence[str]) -> None:
        return None

    def embed(self, texts: Sequence[str]) -> NDArray[np.float64]:
        vectors = np.array(list(self._model.embed(list(texts))), dtype=np.float64)
        return _normalise(vectors)
