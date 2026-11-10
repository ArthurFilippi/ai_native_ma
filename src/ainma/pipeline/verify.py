"""Claim verification. The two pure checks come first, the judge check is added below."""

from __future__ import annotations

import asyncio
import re
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


# ---- binding of a number to its role, period and column (D89) ----------------------------------

_TOP_N = re.compile(
    r"\b(?:top|largest|biggest)\s+(?:two|three|four|five|six|ten|twenty|\d+)\b"
    r"|\b(?:two|three|four|five|six|ten|twenty|\d+)\s+(?:largest|biggest)\b",
    re.IGNORECASE,
)
_SINGLE = re.compile(
    r"\b(?:single\s+largest|largest\s+single|largest|biggest|top|main)\s+"
    r"(?:customer|client|supplier|shareholder)\b",
    re.IGNORECASE,
)
_CLAUSE = re.compile(r"[.;:]\s|,\s*(?:and|while|but|whereas|with)\b|\n")


def _role(text: str) -> str | None:
    """`top_n` for a group (`top five customers`), `single` for one (`largest customer`)."""
    if _TOP_N.search(text):
        return "top_n"
    if _SINGLE.search(text):
        return "single"
    return None


def _clause_at(text: str, position: int) -> str:
    start, end = 0, len(text)
    for match in _CLAUSE.finditer(text):
        if match.end() <= position:
            start = match.end()
        elif match.start() >= position:
            end = match.start()
            break
    return text[start:end]


def _sentence_bounds(text: str, position: int) -> tuple[int, int]:
    start = max(text.rfind(". ", 0, position), text.rfind("\n", 0, position)) + 1
    ends = [i for i in (text.find(". ", position), text.find("\n", position)) if i >= 0]
    return start, min(ends) if ends else len(text)


def _asides(sentence: str, position: int) -> list[tuple[int, int]]:
    """Spans of the parentheses of `sentence` that do not contain `position`."""
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"\([^()]*\)", sentence):
        if not match.start() <= position < match.end():
            spans.append((match.start(), match.end()))
    return spans


def _year_label(value: float) -> str:
    return f"FY{int(value)}"


def _header_years(context: str) -> list[float | None] | None:
    """Year of each cell of the first table header line that names two years or more."""
    for line in context.splitlines():
        if " | " not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        years: list[float | None] = []
        for cell in cells:
            found = [q.value for q in parse_quantities(cell) if q.kind == "year"]
            years.append(found[0] if len(found) == 1 else None)
        if sum(y is not None for y in years) >= 2:
            return years
    return None


def binding_check(claim_text: str, quote: str, context: str = "") -> tuple[bool, str]:
    """Each number of the claim is bound, in the source, to the role and the period the claim
    gives it.

    - Role: a claim about one entity (`largest customer`) cannot rest on a number the source
      gives a group (`top five customers`), and the reverse.
    - Column: in a table row, the year of the number's column (from the header line of the
      chunk) must be a year of the claim.
    - Sentence: when the sentence that holds the number names two years or more, the year
      nearest to the number must be a year of the claim.

    A claim without numbers, or a source that gives the number no role and no period, passes:
    the judge decides on the words.
    """
    claim_quantities = parse_quantities(claim_text)
    numbers = [q for q in claim_quantities if q.kind != "year"]
    if not numbers:
        return True, "no number to bind"
    claim_years = {q.value for q in claim_quantities if q.kind == "year"}
    claim_role = _role(claim_text)
    source = context if quote and quote in context else quote
    offset = source.find(quote) if quote and source is not quote else 0
    found = parse_quantities(quote)
    header = _header_years(context) if context else None
    for number in numbers:
        hits = [q for q in found if q.kind != "year" and quantities_match(number, q)]
        if not hits:
            continue  # numeric_match reports a number that is not in the quote
        problems: list[str] = []
        for hit in hits:
            at = offset + hit.start
            if claim_role is not None:
                role = _role(_clause_at(source, at))
                if role is not None and role != claim_role:
                    group = _TOP_N.search(_clause_at(source, at))
                    what = group.group(0) if group else "a group"
                    problems.append(
                        f"{number.text} is the {what} figure in the source, not a single one"
                        if role == "top_n"
                        else f"{number.text} is a single entity figure in the source"
                    )
                    continue
            line_start = source.rfind("\n", 0, at) + 1
            line_end = source.find("\n", at)
            line = source[line_start : line_end if line_end >= 0 else len(source)]
            if claim_years and header is not None and " | " in line:
                column = source[line_start:at].count("|")
                cells = line.count("|") + 1
                index = column + (len(header) - cells) if cells != len(header) else column
                year = header[index] if 0 <= index < len(header) else None
                if year is not None and year not in claim_years:
                    problems.append(f"{number.text} is in the {_year_label(year)} column")
                    continue
            if claim_years:
                start, end = _sentence_bounds(source, at)
                years = [q for q in parse_quantities(source[start:end]) if q.kind == "year"]
                lo, hi = at - start, at - start + (hit.end - hit.start)
                # a year inside a parenthesis that does not hold the number belongs to the
                # parenthesis (`EUR 182.4 million (FY2023: EUR 168.0 million)`)
                aside = _asides(source[start:end], lo)
                years = [q for q in years if not any(a <= q.start < b for a, b in aside)]
                if len({q.value for q in years}) >= 2:
                    nearest = min(years, key=lambda q: lo - q.end if q.end <= lo else q.start - hi)
                    if nearest.value not in claim_years:
                        problems.append(
                            f"{number.text} is given for {_year_label(nearest.value)} in the source"
                        )
                        continue
            break  # one occurrence bound as the claim says is enough
        else:
            return False, "; ".join(problems)
    return True, "numbers bound to the claimed role and period"


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
    """The checks of spec section 8 in order (span, numbers, binding, judge); a failing check
    stops the chain."""
    checks = [_citation_check(claim, chunks)]
    usage: Usage | None = None
    label: Literal["supported", "partial", "unsupported"] | None = None
    if checks[0].passed:
        quotes = [c.quote for c in claim.citations]
        context = judge_context(claim, chunks)
        passed, detail = numeric_match(claim.text, " ".join(quotes), context)
        checks.append(VerificationCheck(name="numeric_match", passed=passed, detail=detail))
        if passed:
            passed, detail = binding_check(claim.text, " ".join(quotes), context)
            checks.append(VerificationCheck(name="binding", passed=passed, detail=detail))
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
