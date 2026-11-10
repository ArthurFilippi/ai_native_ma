"""Abstention: when to say "not found" instead of writing, and how to pick the threshold.

The pipeline abstains when no supported claim remains or when the best support score of the
retrieved passages is below `tau`. The support score is the retrieval relevance (see D24):
tier and recency say how far to trust a source, not whether the topic is covered, so an old
source must still produce a claim carrying the stale flag rather than an abstention.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ainma.contracts import DocStatus
from ainma.retrieval.engine import SearchHit

REASON_NO_PASSAGE = "No retrieved passage scored above the support threshold."
REASON_NO_CLAIM = "Passages were retrieved but no claim could be written and verified from them."
REASON_ALL_DROPPED = "Every drafted claim failed verification."
REASON_WITHDRAWN = "The only relevant source is a withdrawn document, which is excluded."
REASON_EMPTY = "The question is empty."


def support_score(hit: SearchHit, basis: Literal["relevance", "final"]) -> float:
    """Score compared with `tau`. Withdrawn hits always use relevance: their final score is 0."""
    if basis == "final" and hit.document.status is not DocStatus.WITHDRAWN:
        return hit.passage.final_score
    return hit.passage.components.get("relevance", hit.passage.final_score)


@dataclass(frozen=True)
class TauCalibration:
    tau: float
    false_abstention: float  # share of answerable scores below tau
    correct_abstention: float  # share of unanswerable scores below tau


def calibrate_tau(
    answerable: Sequence[float],
    unanswerable: Sequence[float],
    *,
    max_false_abstention: float = 0.10,
) -> TauCalibration:
    """Largest threshold whose false abstention on answerable queries stays within the target.

    Inputs are the best support score per query (0 when nothing was retrieved). Use DEV queries
    only, then freeze the value. Candidate thresholds are the observed answerable scores.
    """
    if not answerable:
        raise ValueError("at least one answerable score is needed")

    def rate(scores: Sequence[float], tau: float) -> float:
        return sum(s < tau for s in scores) / len(scores) if scores else 0.0

    best = min(answerable)
    for candidate in sorted(set(answerable)):
        if rate(answerable, candidate) <= max_false_abstention:
            best = candidate
    return TauCalibration(
        tau=best,
        false_abstention=rate(answerable, best),
        correct_abstention=rate(unanswerable, best),
    )
