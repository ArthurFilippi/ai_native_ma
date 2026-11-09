"""Verifier quality on the adversarial claims (eval plan section 4).

Positive class: a claim that is not fully supported (`partial` or `unsupported`). The verifier
"flags" a claim when it refuses to pass it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ainma.evaluation.metrics.common import ratio, share

NOT_SUPPORTED = ("partial", "unsupported")


@dataclass(frozen=True)
class VerifierScores:
    recall_unsupported: float | None
    recall_partial: float | None
    recall_not_supported: float | None
    precision: float | None
    false_flag_rate: float | None  # share of fully supported claims that were flagged


def verifier_scores(truth: Sequence[str], flagged: Sequence[bool]) -> VerifierScores:
    if len(truth) != len(flagged):
        raise ValueError("truth and flagged must have the same length")
    pairs = list(zip(truth, flagged, strict=True))

    def recall_of(labels: tuple[str, ...]) -> float | None:
        return share([f for t, f in pairs if t in labels])

    true_positive = sum(1 for t, f in pairs if f and t in NOT_SUPPORTED)
    n_flagged = sum(1 for _, f in pairs if f)
    return VerifierScores(
        recall_unsupported=recall_of(("unsupported",)),
        recall_partial=recall_of(("partial",)),
        recall_not_supported=recall_of(NOT_SUPPORTED),
        precision=ratio(true_positive, n_flagged),
        false_flag_rate=share([f for t, f in pairs if t == "supported"]),
    )


def recall_by_group(
    groups: Sequence[str], truth: Sequence[str], flagged: Sequence[bool]
) -> dict[str, float | None]:
    """Recall of not fully supported claims inside each group (for instance by perturbation)."""
    out: dict[str, float | None] = {}
    for group in sorted(set(groups)):
        flags = [
            f
            for g, t, f in zip(groups, truth, flagged, strict=True)
            if g == group and t in NOT_SUPPORTED
        ]
        out[group] = share(flags)
    return out
