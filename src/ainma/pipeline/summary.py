"""The short summary is built by code from the verified claims, so it can never say more than
the claims do. At most four sentences: disagreements first, then facts, deduction, age, gaps."""

from __future__ import annotations

from ainma.contracts import Claim, ClaimStatus, Contradiction, Flag, MissingInfo


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def build_summary(
    claims: list[Claim],
    contradictions: list[Contradiction],
    missing: list[MissingInfo],
    *,
    scope: str,
) -> str:
    segments: list[str] = []
    contradicted = {side.claim_id for k in contradictions for side in k.sides}
    for contradiction in contradictions:
        sides = " versus ".join(
            f"{side.label} (tier {int(side.citations[0].tier)})" for side in contradiction.sides
        )
        segments.append(
            f"Sources disagree on {contradiction.subject}: {sides}. The system does not pick one."
        )
    sourced = [c for c in claims if c.status is ClaimStatus.SOURCED and c.id not in contradicted]
    segments.extend(_sentence(c.text) for c in sourced[:2])
    inferred = [c for c in claims if c.status is ClaimStatus.INFERRED]
    if inferred:
        segments.append(_sentence(inferred[0].text))
    if any(Flag.STALE in c.flags for c in claims):
        segments.append("Some of the evidence is old: check the dates shown with each source.")
    if missing:
        topics = "; ".join(m.topic for m in missing)
        segments.append(f"Not found in the sources available for {scope}: {topics}.")
    if not segments:
        return f"Not found in the sources available for {scope}. No claim is made."
    return " ".join(segments[:4])
