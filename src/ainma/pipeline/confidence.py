"""One-glance confidence of an answer, computed by code from its evidence (D97).

The level is a reading aid, not a probability. Rules, in order:

- abstained answer: no level (the answer says it found nothing);
- low: no sourced claim, or every sourced claim rests only on tier 4 or 5 sources (press, web),
  or a claim failed verification and was kept as unverified;
- medium: sources disagree (a contradiction), a part of the question is missing, a cited source
  is stale, superseded or withdrawn, or the best support is a single source of tier 3 or worse;
- high: every sourced claim is verified, cites a tier 1 or 2 source, and either two documents
  agree or the source is tier 1, with no contradiction and nothing missing.

The reason lists what decided the level, so the user sees why in one line.
"""

from __future__ import annotations

from typing import Literal

from ainma.contracts import Answer, Claim, ClaimStatus, Flag

Level = Literal["high", "medium", "low"]
_WEAK_FLAGS = {Flag.STALE, Flag.SUPERSEDED, Flag.WITHDRAWN}


def _best_tier(claim: Claim) -> int:
    return min((int(c.tier) for c in claim.citations), default=5)


def _documents(claim: Claim) -> int:
    return len({c.document_id for c in claim.citations})


def answer_confidence(answer: Answer) -> tuple[Level | None, str | None]:
    if answer.abstained:
        return None, None
    sourced = [c for c in answer.claims if c.status is ClaimStatus.SOURCED]
    if not sourced:
        return "low", "No claim is quoted from a source."
    if all(_best_tier(c) >= 4 for c in sourced):
        return "low", "Only press or web sources (tier 4 or 5) support the answer."
    if any(Flag.UNVERIFIED in c.flags for c in sourced):
        return "low", "A claim could not be verified against its source."
    reasons: list[str] = []
    if answer.contradictions:
        reasons.append("sources disagree")
    if answer.missing:
        reasons.append("part of the question is not covered")
    if any(set(c.flags) & _WEAK_FLAGS for c in sourced):
        reasons.append("a source is old, superseded or withdrawn")
    if any(_best_tier(c) >= 3 and _documents(c) < 2 for c in sourced):
        reasons.append("a claim rests on a single source below tier 2")
    if reasons:
        return "medium", "Medium: " + "; ".join(reasons) + "."
    verified = all(c.verification is None or c.verification.supported for c in sourced)
    strong = all(_best_tier(c) <= 2 and (_documents(c) >= 2 or _best_tier(c) == 1) for c in sourced)
    if verified and strong:
        return "high", "High: verified quotes from tier 1 or 2 sources that agree."
    return "medium", "Medium: verified quotes, but from a single deal document or company report."
