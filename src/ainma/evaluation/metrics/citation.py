"""Citation fidelity (eval plan section 4).

A claim `c` matches gold fact `f` when the normalised value of `f` appears in `c` and every
metric and period keyword of `f` appears in `c`. A matched claim is correctly cited when at least
one of its citations points to a chunk of the support set of `f`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ainma.evaluation.metrics.numbers import numbers_covered, value_in_text


@dataclass(frozen=True)
class GoldFact:
    id: str
    value: float
    keywords: tuple[str, ...]
    support_chunk_ids: frozenset[str]


@dataclass(frozen=True)
class CitedClaim:
    """A `SOURCED` claim reduced to what the metric needs."""

    text: str
    chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class QuotedCitation:
    quote: str
    chunk_text: str


@dataclass(frozen=True)
class CitationCounts:
    n_claims: int
    n_correct: int
    n_facts: int
    n_covered: int

    @property
    def precision(self) -> float | None:
        return self.n_correct / self.n_claims if self.n_claims else None

    @property
    def recall(self) -> float | None:
        return self.n_covered / self.n_facts if self.n_facts else None


def claim_matches_fact(text: str, fact: GoldFact) -> bool:
    lowered = text.lower()
    return value_in_text(fact.value, text) and all(k.lower() in lowered for k in fact.keywords)


def citation_counts(claims: Sequence[CitedClaim], facts: Sequence[GoldFact]) -> CitationCounts:
    """Counts behind citation precision and recall for one query.

    A claim matching no gold fact counts as incorrect. A fact is covered when at least one claim
    that matches it cites a chunk of its support set.
    """
    n_correct = 0
    covered: set[str] = set()
    for claim in claims:
        cited = set(claim.chunk_ids)
        correct = False
        for fact in facts:
            if claim_matches_fact(claim.text, fact) and cited & fact.support_chunk_ids:
                correct = True
                covered.add(fact.id)
        n_correct += int(correct)
    return CitationCounts(len(claims), n_correct, len(facts), len(covered))


def claim_is_unsupported(text: str, citations: Sequence[QuotedCitation]) -> bool:
    """True when a quote is not a verbatim substring of its chunk, or when a number of the claim
    appears in none of the quotes."""
    if any(c.quote not in c.chunk_text for c in citations):
        return True
    return not numbers_covered(text, [c.quote for c in citations])
