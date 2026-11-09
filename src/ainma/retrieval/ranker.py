"""Source ranker of spec section 7.

    final = relevance * tier_weight * recency * status + corroboration_bonus
    recency = 0.5 ** (age_days / half_life(doc_type))       age relative to `as_of`
    status  = 1.0 current | 0.2 superseded | 0.0 withdrawn
    corroboration_bonus = 0.05 * min(n_independent_documents_with_same_fact - 1, 3)

`relevance` is the score of the retrieval stage in [0, 1]. Two documents are independent when
they have different ids and different sha256 and neither is `superseded_by` the other.
"""

from __future__ import annotations

from datetime import date

from ainma.contracts import Chunk, DocStatus, DocumentMeta
from ainma.retrieval.config import RankerConfig
from ainma.retrieval.quantities import ExtractedFact


def recency_factor(
    published_on: date | None, doc_type_half_life: float, as_of: date | None, undated: float
) -> float:
    if published_on is None or as_of is None:
        return undated
    age_days = max(0, (as_of - published_on).days)
    return float(0.5 ** (age_days / doc_type_half_life))


def chunk_recency(chunk: Chunk, config: RankerConfig, as_of: date | None) -> float:
    published = chunk.published_on
    return recency_factor(
        published, config.half_life_days[chunk.doc_type], as_of, config.undated_recency
    )


def independent(a: DocumentMeta, b: DocumentMeta) -> bool:
    return (
        a.id != b.id
        and a.sha256 != b.sha256
        and a.superseded_by != b.id
        and b.superseded_by != a.id
    )


def same_fact(a: ExtractedFact, b: ExtractedFact, tolerance: float) -> bool:
    if a.metric != b.metric or a.period != b.period or a.unit != b.unit:
        return False
    scale = max(abs(a.value), abs(b.value))
    return scale == 0.0 or abs(a.value - b.value) / scale <= tolerance


def corroboration_count(
    document: DocumentMeta,
    facts: list[ExtractedFact],
    others: list[tuple[DocumentMeta, list[ExtractedFact]]],
    tolerance: float,
) -> int:
    """Number of other independent documents that state one of `facts` (within tolerance)."""
    agreeing: set[str] = set()
    for other, other_facts in others:
        if not independent(document, other) or other.status is DocStatus.WITHDRAWN:
            continue
        if any(same_fact(f, g, tolerance) for f in facts for g in other_facts):
            agreeing.add(other.id)
    return len(agreeing)


def corroboration_bonus(n_others: int, config: RankerConfig) -> float:
    return config.corroboration_step * min(n_others, config.corroboration_cap)


def final_score(
    *, relevance: float, tier_weight: float, recency: float, status: float, bonus: float
) -> float:
    if status == 0.0:
        return 0.0
    return min(1.0, relevance * tier_weight * recency * status + bonus)
