"""Judge calibration (eval plan section 8): Cohen's kappa, linearly weighted kappa, confusion."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

JUDGE_LABELS = ("supported", "partial", "unsupported")

IntArray = npt.NDArray[np.int64]


def encode(values: Sequence[str], labels: Sequence[str]) -> IntArray:
    index = {label: i for i, label in enumerate(labels)}
    return np.array([index[v] for v in values], dtype=np.int64)


def confusion_counts(a: IntArray, b: IntArray, k: int) -> npt.NDArray[np.float64]:
    """`k x k` counts, rows indexed by `a` (reference), columns by `b`."""
    flat = np.bincount(a * k + b, minlength=k * k)
    return flat.reshape(k, k).astype(np.float64)


def kappa_from_codes(a: IntArray, b: IntArray, k: int, *, weighted: bool = False) -> float | None:
    """`kappa = 1 - sum(w * observed) / sum(w * expected)`. With 0/1 weights this is
    `(p_o - p_e) / (1 - p_e)`; with `|i - j| / (k - 1)` it is the linearly weighted kappa.
    `None` when expected disagreement is zero (one label only)."""
    n = len(a)
    if n == 0:
        return None
    observed = confusion_counts(a, b, k) / n
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0))
    grid = np.abs(np.subtract.outer(np.arange(k), np.arange(k))).astype(np.float64)
    weights = grid / (k - 1) if weighted else (grid > 0).astype(np.float64)
    denominator = float((weights * expected).sum())
    if denominator == 0:
        return None
    return 1.0 - float((weights * observed).sum()) / denominator


def cohen_kappa(
    a: Sequence[str], b: Sequence[str], labels: Sequence[str] = JUDGE_LABELS
) -> float | None:
    return kappa_from_codes(encode(a, labels), encode(b, labels), len(labels))


def weighted_kappa(
    a: Sequence[str], b: Sequence[str], labels: Sequence[str] = JUDGE_LABELS
) -> float | None:
    """Linearly weighted kappa over ordered `labels`."""
    return kappa_from_codes(encode(a, labels), encode(b, labels), len(labels), weighted=True)


def confusion_matrix(
    reference: Sequence[str], predicted: Sequence[str], labels: Sequence[str] = JUDGE_LABELS
) -> list[list[int]]:
    """Rows are reference labels, columns predicted labels, in the order of `labels`."""
    matrix = confusion_counts(encode(reference, labels), encode(predicted, labels), len(labels))
    return [[int(v) for v in row] for row in matrix]
