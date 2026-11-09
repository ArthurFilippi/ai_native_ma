"""Abstention (eval plan section 5).

The pipeline abstains when the best final passage score is below `tau`. A query that retrieved
nothing has no score (`None`) and always abstains. Scores of unanswerable and answerable queries
are kept apart so the tradeoff curve can be drawn.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ainma.evaluation.metrics.common import ratio, share

NO_EVIDENCE = float("-inf")


def _floor(scores: Sequence[float | None]) -> list[float]:
    return [NO_EVIDENCE if s is None else s for s in scores]


@dataclass(frozen=True)
class CurvePoint:
    tau: float
    correct_abstention_rate: float | None  # abstained / unanswerable
    false_abstention_rate: float | None  # abstained / answerable
    precision: float | None  # unanswerable among abstained


def abstention_rates(
    abstained_on_unanswerable: Sequence[bool], abstained_on_answerable: Sequence[bool]
) -> tuple[float | None, float | None]:
    """(correct abstention rate, false abstention rate)."""
    return share(abstained_on_unanswerable), share(abstained_on_answerable)


def rates_at_tau(
    tau: float,
    answerable_scores: Sequence[float | None],
    unanswerable_scores: Sequence[float | None],
) -> CurvePoint:
    """Abstain when `score < tau`."""
    answerable = _floor(answerable_scores)
    unanswerable = _floor(unanswerable_scores)
    abstained_answerable = sum(1 for s in answerable if s < tau)
    abstained_unanswerable = sum(1 for s in unanswerable if s < tau)
    return CurvePoint(
        tau=tau,
        correct_abstention_rate=ratio(abstained_unanswerable, len(unanswerable)),
        false_abstention_rate=ratio(abstained_answerable, len(answerable)),
        precision=ratio(abstained_unanswerable, abstained_unanswerable + abstained_answerable),
    )


def threshold_curve(
    answerable_scores: Sequence[float | None], unanswerable_scores: Sequence[float | None]
) -> list[CurvePoint]:
    """One point per distinct finite score (abstain below it) plus one point above every score
    (abstain on everything)."""
    pooled = set(_floor(answerable_scores) + _floor(unanswerable_scores))
    scores = sorted(pooled - {NO_EVIDENCE})
    taus = [*scores, math.inf]
    return [rates_at_tau(t, answerable_scores, unanswerable_scores) for t in taus]


def choose_tau(
    dev_answerable_scores: Sequence[float | None], target_false_abstention: float
) -> float:
    """Largest-recall threshold whose false abstention rate on dev answerable queries stays at or
    below the target: with `n` queries and `m = floor(target * n)`, `tau` is the (m+1)th smallest
    score, so at most `m` queries score strictly below it. Chosen on dev only, then frozen."""
    if not 0.0 <= target_false_abstention < 1.0:
        raise ValueError("the target false abstention rate must be in [0, 1)")
    scores = sorted(_floor(dev_answerable_scores))
    if not scores:
        raise ValueError("no dev answerable scores to choose a threshold from")
    allowed = int(target_false_abstention * len(scores) + 1e-9)
    return scores[allowed]
