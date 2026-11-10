"""Evidence retrieval for criteria: passages about one buyer, verbatim quotes, citations by code.

Passages come from `search` (the retrieval entry point, so tiers, staleness and contradictions
apply upstream), filtered to the buyer and to documents that are current. The quote of a piece of
evidence is the sentence around a regex match, always a substring of the chunk text, and the
citation offsets are computed from it by `CitationBuilder`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from ainma.contracts import AccessContext, BuyerProfile, Chunk, Citation, DocStatus
from ainma.kpi.sources import CitationBuilder, SearchFn, SearchHitLike, resolve_search
from ainma.store import Store

__all__ = [
    "CitationBuilder",
    "Evidence",
    "EvidenceFinder",
    "SearchFn",
    "SearchHitLike",
    "resolve_search",
    "sentence_around",
]

_SENTENCE_END = re.compile(r"(?<=[.!?])\s|\n")
_MAX_QUOTE = 400


def sentence_around(text: str, start: int, end: int) -> tuple[int, int]:
    """Bounds of the sentence (or line) containing `text[start:end]`, trimmed and capped."""
    left = max(text.rfind("\n", 0, start) + 1, 0)
    for match in _SENTENCE_END.finditer(text, 0, start):
        left = max(left, match.end())
    following = _SENTENCE_END.search(text, end)
    right = following.start() if following else len(text)
    while left < right and text[left].isspace():
        left += 1
    while right > left and text[right - 1].isspace():
        right -= 1
    if right - left > _MAX_QUOTE:
        left, right = max(left, start - 100), min(right, end + 100)
    return left, right


@dataclass(frozen=True)
class Evidence:
    chunk: Chunk
    quote: str
    match: re.Match[str]


class EvidenceFinder:
    def __init__(
        self, *, search: SearchFn, store: Store, access: AccessContext, deal_id: str
    ) -> None:
        self._search = search
        self._store = store
        self._access = access
        self.deal_id = deal_id
        self._citations = CitationBuilder(store, access)

    async def _current(self, chunks: Iterable[Chunk]) -> list[Chunk]:
        kept: list[Chunk] = []
        for chunk in chunks:
            meta = await self._citations.document(chunk.document_id)
            if meta.status is DocStatus.CURRENT:
                kept.append(chunk)
        return kept

    async def _retrieve(self, query: str) -> list[Chunk]:
        hits = await self._search(
            query, store=self._store, access=self._access, deal_id=self.deal_id
        )
        return await self._current(hit.chunk for hit in hits)

    async def buyer_chunks(self, buyer: BuyerProfile, topic: str) -> list[Chunk]:
        """Retrieved current passages about `buyer`: by entity id, or by name in the text."""
        name = buyer.name.lower()
        chunks = await self._retrieve(f"{buyer.name} {topic}")
        return [c for c in chunks if c.entity_id == buyer.id or name in c.text.lower()]

    async def deal_chunks(self, topic: str) -> list[Chunk]:
        """Retrieved current passages from the deal's own documents."""
        chunks = await self._retrieve(topic)
        return [c for c in chunks if c.deal_id == self.deal_id]

    @staticmethod
    def find(chunks: Iterable[Chunk], pattern: re.Pattern[str]) -> list[Evidence]:
        """Every match of `pattern`, in passage rank order, one piece of evidence per match."""
        found: list[Evidence] = []
        for chunk in chunks:
            for match in pattern.finditer(chunk.text):
                left, right = sentence_around(chunk.text, match.start(), match.end())
                found.append(Evidence(chunk, chunk.text[left:right], match))
        return found

    async def cite(self, evidence: Evidence) -> Citation:
        return await self._citations.build(evidence.chunk, evidence.quote)
