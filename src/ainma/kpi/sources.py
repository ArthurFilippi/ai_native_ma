"""Retrieval and citation helpers shared by KPI extraction and screening evidence.

`SearchFn` is the exact shape of `ainma.retrieval.search` as far as this package uses it. The real
function is resolved lazily by `resolve_search`, so this package never imports the retrieval
package at import time and tests can inject a deterministic searcher.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Protocol, cast

from ainma.contracts import (
    TIER_BY_DOCTYPE,
    AccessContext,
    Chunk,
    Citation,
    DocumentMeta,
    RankedPassage,
)
from ainma.store import Store


class SearchHitLike(Protocol):
    """The part of `SearchHit` used here: the chunk and its ranking explanation."""

    @property
    def chunk(self) -> Chunk: ...

    @property
    def passage(self) -> RankedPassage: ...


class SearchFn(Protocol):
    async def __call__(
        self, query: str, *, store: Store, access: AccessContext, deal_id: str | None
    ) -> Sequence[SearchHitLike]: ...


def resolve_search() -> SearchFn:
    """Return `ainma.retrieval.search`, failing loudly when the retrieval package is absent."""
    try:
        module = importlib.import_module("ainma.retrieval")
        return cast(SearchFn, module.search)
    except (ImportError, AttributeError) as error:
        raise RuntimeError(
            "ainma.retrieval.search is not available: pass `search=` explicitly or merge `core`"
        ) from error


class CitationBuilder:
    """Builds `Citation` objects from a chunk and a verbatim quote. Code, not a model, owns the
    offsets: they are `chunk.char_start + chunk.text.index(quote)` (store invariant D04)."""

    def __init__(self, store: Store, access: AccessContext) -> None:
        self._store = store
        self._access = access
        self._documents: dict[str, DocumentMeta] = {}

    async def document(self, document_id: str) -> DocumentMeta:
        if document_id not in self._documents:
            meta = await self._store.get_document(document_id, self._access)
            if meta is None:
                raise LookupError(f"document {document_id} is not visible to this user")
            self._documents[document_id] = meta
        return self._documents[document_id]

    async def build(self, chunk: Chunk, quote: str) -> Citation:
        if not quote:
            raise ValueError("a citation needs a non-empty quote")
        offset = chunk.text.index(quote)
        meta = await self.document(chunk.document_id)
        return Citation(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            doc_title=meta.title,
            doc_type=chunk.doc_type,
            tier=TIER_BY_DOCTYPE[chunk.doc_type],
            published_on=chunk.published_on,
            page=chunk.page,
            char_start=chunk.char_start + offset,
            char_end=chunk.char_start + offset + len(quote),
            quote=quote,
        )
