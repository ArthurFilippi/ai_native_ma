"""Screening criterion agreement with the buyer truth table (statuses as strings)."""

from __future__ import annotations

from collections.abc import Sequence
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
