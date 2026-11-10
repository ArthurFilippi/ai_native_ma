"""A read-only view of a store restricted to the documents of one entity or of one deal.

The search entry point ranks every chunk the user may see (the deal and the general layer), so a
query about one buyer competes with the documents of the 39 others, and a question about the
deal's revenue competes with the buyers' annual reports. This view narrows the candidate set
before ranking, through the public store interface: the access filter stays inside the wrapped
store's own query, the view only removes chunks and documents outside the scope. Writes are not
offered.
"""

from __future__ import annotations

from collections.abc import Sequence

from ainma.contracts import (
    AccessContext,
    BuyerProfile,
    Chunk,
    Deal,
    DocType,
    DocumentMeta,
    Membership,
    User,
)
from ainma.store import Store


class ScopedStore:
    """Implements `Store`; `candidates` and `list_documents` keep only the scope's own items."""

    def __init__(self, inner: Store, *, entity_id: str | None = None, deal_id: str | None = None):
        if (entity_id is None) == (deal_id is None):
            raise ValueError("give exactly one of entity_id and deal_id")
        self._inner = inner
        self.entity_id = entity_id
        self.deal_id = deal_id

    def _in_scope(self, item: Chunk | DocumentMeta) -> bool:
        if self.entity_id is not None:
            return item.entity_id == self.entity_id
        return item.deal_id == self.deal_id

    async def candidates(
        self,
        access: AccessContext,
        *,
        deal_id: str | None,
        doc_types: Sequence[DocType] | None = None,
    ) -> list[Chunk]:
        chunks = await self._inner.candidates(access, deal_id=deal_id, doc_types=doc_types)
        return [c for c in chunks if self._in_scope(c)]

    async def list_documents(
        self, access: AccessContext, deal_id: str | None
    ) -> list[DocumentMeta]:
        documents = await self._inner.list_documents(access, deal_id)
        return [d for d in documents if self._in_scope(d)]

    async def get_chunk(self, chunk_id: str, access: AccessContext) -> Chunk | None:
        return await self._inner.get_chunk(chunk_id, access)

    async def get_page(self, document_id: str, page: int, access: AccessContext) -> str | None:
        return await self._inner.get_page(document_id, page, access)

    async def get_document(self, document_id: str, access: AccessContext) -> DocumentMeta | None:
        return await self._inner.get_document(document_id, access)

    async def get_deal(self, deal_id: str, access: AccessContext) -> Deal | None:
        return await self._inner.get_deal(deal_id, access)

    async def list_deals(self, access: AccessContext) -> list[Deal]:
        return await self._inner.list_deals(access)

    async def access_for(self, user_id: str) -> AccessContext:
        return await self._inner.access_for(user_id)

    async def list_users(self) -> list[User]:
        return await self._inner.list_users()

    async def list_buyers(self) -> list[BuyerProfile]:
        return await self._inner.list_buyers()

    async def _read_only(self) -> None:
        raise PermissionError("an entity scoped store view is read only")

    async def put_user(self, user: User) -> None:
        await self._read_only()

    async def put_deal(self, deal: Deal) -> None:
        await self._read_only()

    async def put_membership(self, membership: Membership) -> None:
        await self._read_only()

    async def put_buyer(self, buyer: BuyerProfile) -> None:
        await self._read_only()

    async def put_document(self, meta: DocumentMeta, pages: Sequence[str]) -> None:
        await self._read_only()

    async def put_chunks(self, chunks: Sequence[Chunk]) -> None:
        await self._read_only()

    async def close(self) -> None:
        return None
