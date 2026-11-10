"""Screening criterion agreement with the buyer truth table (statuses as strings)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ainma.evaluation.metrics.common import ratio


@dataclass(frozen=True)
class ScreeningScores:
    agreement: float | None  # predicted == truth over all cells, unknown included
    unknown_rate: float | None  # the safe answer
    accuracy_known: float | None  # correct among cells where a definite status was predicted
    false_met_rate: float | None  # predicted met although the truth is not met: the unsafe error


def screening_scores(pairs: Sequence[tuple[str, str]]) -> ScreeningScores:
    """`pairs` holds (truth status, predicted status) per buyer and criterion."""
    known = [(t, p) for t, p in pairs if p != "unknown"]
    met = [(t, p) for t, p in pairs if p == "met"]
    return ScreeningScores(
        agreement=ratio(sum(1 for t, p in pairs if t == p), len(pairs)),
        unknown_rate=ratio(len(pairs) - len(known), len(pairs)),
        accuracy_known=ratio(sum(1 for t, p in known if t == p), len(known)),
        false_met_rate=ratio(sum(1 for t, _ in met if t != "met"), len(met)),
    )


def _ranks(values: Sequence[float]) -> list[float]:
    """Average ranks (1 based), ties share the mean of their positions."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Spearman's rho with average ranks for ties; None when a side is constant or too short."""
    if len(a) != len(b) or len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return None
    return float(cov / (va * vb) ** 0.5)


def true_scores(
    truth: Mapping[str, Mapping[str, str]], weights: Mapping[str, float]
) -> dict[str, float]:
    """Score of each buyer from the truth statuses: met weight over the weight of the criteria
    the truth covers for it (the score a screener with full evidence would give)."""
    out: dict[str, float] = {}
    for buyer, statuses in truth.items():
        total = sum(weights.get(k, 0.0) for k in statuses)
        met = sum(weights.get(k, 0.0) for k, v in statuses.items() if v == "met")
        out[buyer] = met / total if total > 0 else 0.0
    return out


def ranking_agreement(order: Sequence[str], truth_score: Mapping[str, float]) -> float | None:
    """Spearman's rho between the system's order (first is best) and the truth score, over the
    buyers of the truth; buyers the system did not rank share the last position."""
    position = {buyer: i for i, buyer in enumerate(order)}
    last = len(order)
    buyers = sorted(truth_score)
    return spearman(
        [-float(position.get(b, last)) for b in buyers], [truth_score[b] for b in buyers]
    )
