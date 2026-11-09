"""Store interface. The access predicate is applied inside `candidates`, before any scoring."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ainma.contracts import (
    AccessContext,
    Chunk,
    Deal,
    DocType,
    DocumentMeta,
    Membership,
    User,
)


class UnknownUserError(KeyError):
    """The user id is not registered (distinct from a user without memberships)."""


class Store(Protocol):
    async def put_user(self, user: User) -> None: ...
    async def put_deal(self, deal: Deal) -> None: ...
    async def put_membership(self, membership: Membership) -> None: ...
    async def put_document(self, meta: DocumentMeta, pages: Sequence[str]) -> None: ...
    async def put_chunks(self, chunks: Sequence[Chunk]) -> None: ...

    async def candidates(
        self,
        access: AccessContext,
        *,
        deal_id: str | None,
        doc_types: Sequence[DocType] | None = None,
    ) -> list[Chunk]:
        """Chunks of `deal_id` (when given) plus the general layer, each only if `access` allows."""
        ...

    async def get_chunk(self, chunk_id: str, access: AccessContext) -> Chunk | None: ...
    async def get_page(self, document_id: str, page: int, access: AccessContext) -> str | None: ...
    async def get_document(
        self, document_id: str, access: AccessContext
    ) -> DocumentMeta | None: ...
    async def list_documents(
        self, access: AccessContext, deal_id: str | None
    ) -> list[DocumentMeta]: ...
    async def get_deal(self, deal_id: str, access: AccessContext) -> Deal | None: ...
    async def list_deals(self, access: AccessContext) -> list[Deal]: ...
    async def access_for(self, user_id: str) -> AccessContext: ...
    async def list_users(self) -> list[User]: ...
    async def close(self) -> None: ...
