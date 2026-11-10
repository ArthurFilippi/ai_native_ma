"""Contradictions: the same keyed fact stated differently by independent documents.

Facts `(entity, metric, period)` come from the quotes of the supported claims (the LLM task
`extract_facts`). Two entries conflict when their documents are independent (different id and
sha256, not linked by `superseded_by`) and their values differ by more than the tolerance
(default 0.5 percent). Entries of superseded or withdrawn documents are left out: a replaced or
retracted source is flagged, it does not contradict. The system shows both sides and never picks
a winner; `stronger_side` (tier weight times recency) is informative only.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from ainma.contracts import (
    Chunk,
    Citation,
    Claim,
    ClaimStatus,
    Contradiction,
    ContradictionSide,
    DocStatus,
    DocumentMeta,
)
from ainma.llm.base import LLM, Usage
from ainma.llm.tasks import TASK_EXTRACT_FACTS
from ainma.pipeline import prompts
from ainma.pipeline.schemas import ExtractFactsRequest, ExtractFactsResult, FactItem
from ainma.retrieval.config import RankerConfig
from ainma.retrieval.lexicon import METRIC_BY_KEY
from ainma.retrieval.quantities import STATIC_PERIOD, parse_quantities
from ainma.retrieval.ranker import independent, recency_factor


@dataclass(frozen=True)
class ClaimFact:
    claim_id: str
    citation: Citation
    fact: FactItem
    entity: str
    document: DocumentMeta


@dataclass
class FactIndex:
    entries: list[ClaimFact] = field(default_factory=list)
    usages: list[Usage] = field(default_factory=list)


async def extract_facts(llm: LLM, text: str) -> tuple[list[FactItem], Usage]:
    result, usage = await llm.complete_json(
        task=TASK_EXTRACT_FACTS,
        system=prompts.EXTRACT_FACTS,
        user=ExtractFactsRequest(text=text).model_dump_json(),
        schema=ExtractFactsResult,
        stage="contradictions",
    )
    return result.facts, usage


def _as_written(fact: FactItem, quote: str) -> str | None:
    """The amount as the source writes it (`EUR 179 million`), for the label of a side."""
    for quantity in parse_quantities(quote):
        value = (
            quantity.value / 1e6
            if fact.unit.endswith(" m") and quantity.scale != 1.0
            else quantity.raw
        )
        if math.isclose(value, fact.value, rel_tol=1e-6):
            return quantity.text
    return None


def entity_of(chunk: Chunk) -> str:
    return chunk.entity_id or chunk.deal_id or "general"


async def collect_claim_facts(
    claims: Sequence[Claim],
    *,
    chunks: Mapping[str, Chunk],
    documents: Mapping[str, DocumentMeta],
    llm: LLM,
) -> FactIndex:
    """Keyed facts of every sourced claim, one extraction per distinct claim text.

    The facts are read from the claim, not from its quote: the claim names the metric and the
    period the question asked for (`revenue for FY2024`), while a quote may be a table row or a
    press sentence that leaves the period implicit. The verifier has already established that
    the quote supports the claim. Each fact is attached to every document the claim cites.
    """
    ordered = sorted({c.text for c in claims if c.status is ClaimStatus.SOURCED})
    extracted = await asyncio.gather(*(extract_facts(llm, t) for t in ordered))
    facts_of = {t: facts for t, (facts, _) in zip(ordered, extracted, strict=True)}
    index = FactIndex(usages=[usage for _, usage in extracted])
    for claim in claims:
        if claim.status is not ClaimStatus.SOURCED:
            continue
        for citation in claim.citations:
            chunk = chunks[citation.chunk_id]
            for fact in facts_of[claim.text]:
                index.entries.append(
                    ClaimFact(
                        claim_id=claim.id,
                        citation=citation,
                        fact=fact.model_copy(
                            update={"label": _as_written(fact, citation.quote) or fact.label}
                        ),
                        entity=entity_of(chunk),
                        document=documents[citation.document_id],
                    )
                )
    return index


def _strength(entry: ClaimFact, ranker: RankerConfig, as_of: date | None) -> float:
    citation = entry.citation
    weight = ranker.tier_weights[citation.tier]
    recency = recency_factor(
        citation.published_on,
        ranker.half_life_days[citation.doc_type],
        as_of,
        ranker.undated_recency,
    )
    return max(0.0, min(1.0, weight * recency))


def _clusters(entries: list[ClaimFact], tolerance: float) -> list[list[ClaimFact]]:
    clusters: list[list[ClaimFact]] = []
    for entry in sorted(entries, key=lambda e: e.fact.value):
        if clusters:
            anchor = clusters[-1][0].fact.value
            scale = max(abs(anchor), abs(entry.fact.value))
            if scale == 0.0 or abs(entry.fact.value - anchor) / scale <= tolerance:
                clusters[-1].append(entry)
                continue
        clusters.append([entry])
    return clusters


def detect_contradictions(
    index: FactIndex,
    *,
    ranker: RankerConfig,
    as_of: date | None,
    tolerance: float,
    subject_name: str,
) -> list[Contradiction]:
    groups: dict[tuple[str, str, str, str], list[ClaimFact]] = {}
    for entry in index.entries:
        if entry.document.status is not DocStatus.CURRENT:
            continue
        period = entry.fact.period or STATIC_PERIOD
        key = (entry.entity, entry.fact.metric, period, entry.fact.unit)
        groups.setdefault(key, []).append(entry)

    found: list[Contradiction] = []
    for key in sorted(groups):
        clusters = _clusters(groups[key], tolerance)
        involved: set[int] = set()
        for i, first in enumerate(clusters):
            for j in range(i + 1, len(clusters)):
                if any(independent(a.document, b.document) for a in first for b in clusters[j]):
                    involved.update((i, j))
        if len(involved) < 2:
            continue
        sides: list[ContradictionSide] = []
        for i in sorted(involved):
            best = max(clusters[i], key=lambda e: _strength(e, ranker, as_of))
            citations: list[Citation] = []
            for entry in clusters[i]:
                if entry.citation not in citations:
                    citations.append(entry.citation)
            sides.append(
                ContradictionSide(
                    label=best.fact.label,
                    claim_id=best.claim_id,
                    citations=citations,
                    strength=_strength(best, ranker, as_of),
                )
            )
        sides.sort(key=lambda side: -side.strength)  # strongest first, stable on ties
        stronger: int | None = 0 if sides[0].strength - sides[1].strength > 1e-9 else None
        _, metric, period, _ = key
        label = METRIC_BY_KEY[metric].label if metric in METRIC_BY_KEY else metric
        found.append(
            Contradiction(
                id=f"k{len(found) + 1}",
                subject=f"{subject_name} {period} {label}",
                sides=sides,
                stronger_side=stronger,
            )
        )
    return found
