"""Evidence retrieval for criteria: passages about one buyer, verbatim quotes, citations by code.

Passages come from `search` (the retrieval entry point, so tiers, staleness and contradictions
apply upstream), filtered to the buyer and to documents that are current. The quote of a piece of
evidence is the sentence around a regex match, always a substring of the chunk text, and the
citation offsets are computed from it by `CitationBuilder`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ainma.contracts import AccessContext, BuyerProfile, Chunk, Citation, DocStatus
from ainma.kpi.scope import ScopedStore
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
_TARGET_SENTENCE = re.compile(
    r"[ \t]+(?:The\s+)?(?:target|acquired\s+(?:company|business))\b[^\n]*?[.!?](?=\s|$)"
)


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

    async def _retrieve(self, query: str, store: Store | None = None) -> list[Chunk]:
        hits = await self._search(
            query, store=store or self._store, access=self._access, deal_id=self.deal_id
        )
        return await self._current(hit.chunk for hit in hits)

    async def buyer_chunks(self, buyer: BuyerProfile, topic: str) -> list[Chunk]:
        """Retrieved current passages about `buyer`.

        The ranking runs over the documents whose `entity_id` is the buyer (the access filter is
        applied by the store before that), so another buyer's documents cannot crowd them out.
        Only when the buyer has no document under its id (entity ids absent from the corpus) the
        query runs over the whole scope and keeps the passages that name the buyer.
        """
        query = f"{buyer.name} {topic}"
        scoped = await self._retrieve(query, ScopedStore(self._store, entity_id=buyer.id))
        if scoped:
            return scoped
        name = buyer.name.lower()
        return [c for c in await self._retrieve(query) if name in c.text.lower()]

    async def deal_chunks(self, topic: str) -> list[Chunk]:
        """Retrieved current passages from the deal's own documents (buyer documents, which
        belong to no deal, cannot crowd them out)."""
        return await self._retrieve(topic, ScopedStore(self._store, deal_id=self.deal_id))

    @staticmethod
    def find(
        chunks: Iterable[Chunk], pattern: re.Pattern[str] | Sequence[re.Pattern[str]]
    ) -> list[Evidence]:
        """Every match of `pattern` (or of any of several patterns), in passage rank order, one
        piece of evidence per match."""
        patterns = [pattern] if isinstance(pattern, re.Pattern) else list(pattern)
        found: list[Evidence] = []
        for chunk in chunks:
            for each in patterns:
                for match in each.finditer(chunk.text):
                    left, right = sentence_around(chunk.text, match.start(), match.end())
                    found.append(Evidence(chunk, chunk.text[left:right], match))
        return found

    @staticmethod
    def with_target_sentence(evidence: Evidence) -> Evidence:
        """Extend the quote over the next sentence when it describes `the target` (a news item
        says `X completes acquisition of Y.` and then `The target is a ... company.`). The quote
        stays one contiguous span of the chunk."""
        text = evidence.chunk.text
        start = text.find(evidence.quote)
        following = _TARGET_SENTENCE.match(text, start + len(evidence.quote))
        if start < 0 or following is None:
            return evidence
        return Evidence(evidence.chunk, text[start : following.end()].rstrip(), evidence.match)

    async def cite(self, evidence: Evidence) -> Citation:
        return await self._citations.build(evidence.chunk, evidence.quote)

    async def cite_quote(self, chunk: Chunk, quote: str) -> Citation:
        """Citation of a verbatim `quote` of `chunk` (the caller checked that it is a span)."""
        return await self._citations.build(chunk, quote)

    @property
    def access(self) -> AccessContext:
        return self._access
