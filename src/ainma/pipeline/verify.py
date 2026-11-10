"""Claim verification. The two pure checks come first, the judge check is added below."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from ainma.contracts import (
    Chunk,
    Claim,
    ClaimStatus,
    Flag,
    Verification,
    VerificationCheck,
)
from ainma.llm.base import LLM, Usage
from ainma.llm.tasks import TASK_JUDGE
from ainma.pipeline import prompts
from ainma.pipeline.schemas import DroppedClaim, JudgeRequest, JudgeResult
from ainma.retrieval.quantities import format_number, parse_quantities, quantities_match


def verbatim_span(quote: str, chunk_text: str) -> bool:
    """The quote is a non empty exact substring of the chunk text."""
    return bool(quote) and quote in chunk_text


def numeric_match(claim_text: str, quote: str, context: str = "") -> tuple[bool, str]:
    """Every number of the claim appears in the quote after unit and scale normalisation.

    `EUR 182.4 million`, `182.4m` and a bare table cell `182.4` agree; `1.8 billion` equals
    `1,800 million`; a percent never matches a currency amount; `FY2024` and `2024` are the same
    year. A claim without numbers passes (the judge decides on the words). Binding a number to its
    metric and period inside a quote that holds several is the judge's job, not this check's.

    A quote that states no year at all (a table row `Revenue | 140.1 | 152.6`) takes its period
    from the header of the chunk it comes from: with `context` (the chunk) the years of the claim
    are then looked up there. A quote that states another year is never rescued by the context. A
    source that states no year at all leaves the year of the claim unchecked (an undated press
    sentence is evidence, not a period); the judge still compares the periods that are stated.
    """
    claim_numbers = parse_quantities(claim_text)
    if not claim_numbers:
        return True, "no number in claim"
    quote_numbers = parse_quantities(quote)
    pool = quote_numbers
    if not any(q.kind == "year" for q in quote_numbers):
        context_years = [q for q in parse_quantities(context) if q.kind == "year"]
        if context_years:
            pool = [*quote_numbers, *context_years]
        elif context:
            # no year anywhere in the source (`X is reported to manage roughly EUR 680 million`):
            # the period of the claim can be neither confirmed nor contradicted by this check
            claim_numbers = [q for q in claim_numbers if q.kind != "year"]
    missing = [q for q in claim_numbers if not any(quantities_match(q, other) for other in pool)]
    if missing:
        return False, "not found in quote: " + ", ".join(q.text for q in missing)
    return True, ", ".join(format_number(q.raw) for q in claim_numbers) + " found in span"


# ---- claim verification -------------------------------------------------------------------------


@dataclass
class VerifyOutcome:
    kept: list[Claim]
    dropped: list[DroppedClaim]
    usages: list[Usage] = field(default_factory=list)


def _citation_check(claim: Claim, chunks: Mapping[str, Chunk]) -> VerificationCheck:
    for citation in claim.citations:
        chunk = chunks.get(citation.chunk_id)
        if chunk is None:
            return VerificationCheck(
                name="verbatim_span", passed=False, detail=f"unknown chunk {citation.chunk_id}"
            )
        if not verbatim_span(citation.quote, chunk.text):
            return VerificationCheck(
                name="verbatim_span", passed=False, detail="quote is not a span of the chunk"
            )
        start = citation.char_start - chunk.char_start
        if chunk.text[start : start + len(citation.quote)] != citation.quote:
            return VerificationCheck(
                name="verbatim_span", passed=False, detail="offsets do not point at the quote"
            )
    return VerificationCheck(name="verbatim_span", passed=True)


def judge_context(claim: Claim, chunks: Mapping[str, Chunk]) -> str:
    """What the judge may read besides the quotes: each cited chunk."""
    return "\n\n".join(chunks[c.chunk_id].text for c in claim.citations)


async def verify_claim(
    claim: Claim, *, chunks: Mapping[str, Chunk], llm: LLM
) -> tuple[Verification, Usage | None]:
    """The three checks of spec section 8 in order; a failing check stops the chain."""
    checks = [_citation_check(claim, chunks)]
    usage: Usage | None = None
    label: Literal["supported", "partial", "unsupported"] | None = None
    if checks[0].passed:
        quotes = [c.quote for c in claim.citations]
        context = judge_context(claim, chunks)
        passed, detail = numeric_match(claim.text, " ".join(quotes), context)
        checks.append(VerificationCheck(name="numeric_match", passed=passed, detail=detail))
        if passed:
            request = JudgeRequest(claim=claim.text, quotes=quotes, context=context)
            result, usage = await llm.complete_json(
                task=TASK_JUDGE,
                system=prompts.JUDGE,
                user=request.model_dump_json(),
                schema=JudgeResult,
                stage="verify",
            )
            label = result.label
            checks.append(
                VerificationCheck(
                    name="judge", passed=result.label == "supported", detail=result.rationale
                )
            )
    supported = all(check.passed for check in checks)
    return Verification(supported=supported, checks=checks, judge_label=label), usage


async def verify_claims(
    claims: list[Claim],
    *,
    chunks: Mapping[str, Chunk],
    llm: LLM,
    drop_unverified: bool,
    concurrency: int = 8,
) -> VerifyOutcome:
    """Verify every SOURCED claim. Failing claims are dropped, or kept with `Flag.UNVERIFIED`.
    An INFERRED claim survives only while every claim it derives from does."""
    gate = asyncio.Semaphore(concurrency)

    async def run(claim: Claim) -> tuple[Verification, Usage | None]:
        async with gate:
            return await verify_claim(claim, chunks=chunks, llm=llm)

    sourced = [c for c in claims if c.status is ClaimStatus.SOURCED]
    results = await asyncio.gather(*(run(c) for c in sourced))
    verdict = {c.id: r for c, r in zip(sourced, results, strict=True)}
    outcome = VerifyOutcome(kept=[], dropped=[], usages=[u for _, u in results if u is not None])
    alive: set[str] = set()
    for claim in claims:
        if claim.status is ClaimStatus.SOURCED:
            verification, _ = verdict[claim.id]
            updated = claim.model_copy(update={"verification": verification})
            if verification.supported:
                alive.add(claim.id)
            elif drop_unverified:
                failed = next(c for c in verification.checks if not c.passed)
                reason = f"{failed.name}: {failed.detail}".strip(": ")
                outcome.dropped.append(
                    DroppedClaim(text=claim.text, stage="verifier", reason=reason)
                )
                continue
            else:
                alive.add(claim.id)
                updated = updated.model_copy(update={"flags": [*claim.flags, Flag.UNVERIFIED]})
            outcome.kept.append(updated)
        elif all(p in alive for p in claim.derived_from):
            alive.add(claim.id)
            outcome.kept.append(claim)
        else:
            outcome.dropped.append(
                DroppedClaim(
                    text=claim.text, stage="verifier", reason="a claim it derives from was dropped"
                )
            )
    return outcome
