"""Deterministic keyword searcher with the shape of `ainma.retrieval.search`, for tests.

It reads candidates through the store (so the access filter applies), scores each chunk by the
number of distinct query words it contains, breaks ties by source tier then chunk id, and returns
the top ten. It is a stand-in until `core` merges, not a retrieval system.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ainma.contracts import TIER_BY_DOCTYPE, AccessContext, Chunk, RankedPassage
from ainma.store import Store

_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class KeywordHit:
    chunk: Chunk
    passage: RankedPassage


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2}


async def keyword_search(
    query: str, *, store: Store, access: AccessContext, deal_id: str | None
) -> list[KeywordHit]:
    wanted = _words(query)
    scored: list[tuple[int, int, str, Chunk]] = []
    for chunk in await store.candidates(access, deal_id=deal_id):
        overlap = len(wanted & _words(chunk.text))
        if overlap:
            tier = int(TIER_BY_DOCTYPE[chunk.doc_type])
            scored.append((-overlap, tier, chunk.id, chunk))
    scored.sort(key=lambda row: row[:3])
    hits: list[KeywordHit] = []
    for rank, (negative, _, _, chunk) in enumerate(scored[:10], start=1):
        passage = RankedPassage(
            chunk_id=chunk.id,
            rank=rank,
            final_score=float(-negative),
            components={"keyword_overlap": float(-negative)},
            explanation=f"{-negative} query words in the passage",
        )
        hits.append(KeywordHit(chunk=chunk, passage=passage))
    return hits
