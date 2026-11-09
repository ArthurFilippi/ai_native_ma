"""Contradiction detection (eval plan section 6).

`planted_detected[i]` is true when the system surfaced a contradiction between the documents of
planted pair `i`. `control_flagged[j]` is true when it surfaced one between the documents of
consistent control `j` (a false positive).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ainma.evaluation.metrics.common import ratio, share


@dataclass(frozen=True)
class ContradictionScores:
    recall: float | None
    false_positive_rate: float | None
    precision: float | None
    f1: float | None


def contradiction_scores(
    planted_detected: Sequence[bool], control_flagged: Sequence[bool]
) -> ContradictionScores:
    true_positive = sum(1 for d in planted_detected if d)
    false_positive = sum(1 for f in control_flagged if f)
    recall = share(planted_detected)
    precision = ratio(true_positive, true_positive + false_positive)
    f1: float | None = None
    if recall is not None and precision is not None and recall + precision > 0:
        f1 = 2 * precision * recall / (precision + recall)
    return ContradictionScores(
        recall=recall,
        false_positive_rate=share(control_flagged),
        precision=precision,
        f1=f1,
    )
