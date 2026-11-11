"""Postgres store (Supabase or any Postgres 14+), behind the same `Store` interface (D101).

Same tables and the same access predicate as the SQLite store: `access_clause` and
`scope_clause` build the SQL in one place, and this module only renumbers their `?` markers into
`$1, $2, ...`. The predicate is part of every read query, before any scoring, exactly as with
SQLite. Bodies are stored as JSON text so the two backends hold the same bytes; `schema.sql`
(`postgres_schema.sql`) creates the tables and can be pasted into the Supabase SQL editor.

Connect with `DATABASE_URL` (`postgresql://user:password@host:5432/postgres`; on Supabase, the
connection string of the project, pooler or direct). The password lives in `.env` only.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from ainma.contracts import (
    AccessContext,
    BuyerProfile,
    Chunk,
    Deal,
    DocType,
    DocumentMeta,
    Membership,
    Role,
    User,
)
from ainma.store.access import access_clause, scope_clause
from ainma.store.base import UnknownUserError

SCHEMA_PATH = Path(__file__).with_name("postgres_schema.sql")
_CHUNK_COLUMNS = (
    "id, document_id, deal_id, entity_id, page, char_start, char_end, text, kind, "
    "doc_type, published_on"
)


def numbered(sql: str) -> str:
    """`?` markers become `$1, $2, ...` in order; the SQLite false literal `0` becomes FALSE."""
    counter = iter(range(1, 10_000))
    sql = re.sub(r"\?", lambda _: f"${next(counter)}", sql)
    sql = re.sub(r"\bWHERE 0\b", "WHERE FALSE", sql)
    return re.sub(r"\bAND 0\b", "AND FALSE", sql)


def _clause(sql: str) -> str:
    return "FALSE" if sql == "0" else sql


def _chunk(row: Any) -> Chunk:
    published = row["published_on"]
    return Chunk(
        id=row["id"],
        document_id=row["document_id"],
        deal_id=row["deal_id"],
        entity_id=row["entity_id"],
        page=row["page"],
        char_start=row["char_start"],
        char_end=row["char_end"],
        text=row["text"],
        kind=row["kind"],
        doc_type=DocType(row["doc_type"]),
        published_on=date.fromisoformat(published) if published else None,
    )


class PostgresStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    @classmethod
    async def open(cls, dsn: str, *, create_schema: bool = True) -> PostgresStore:
        try:
            import asyncpg  # type: ignore[import-untyped,unused-ignore]
        except ImportError as error:  # pragma: no cover - depends on the optional extra
            raise ImportError("the postgres store needs: pip install 'ainma[postgres]'") from error
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        if create_schema:
            async with pool.acquire() as conn:
                await conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def _fetch(self, sql: str, *params: object) -> list[Any]:
        async with self._pool.acquire() as conn:
            return list(await conn.fetch(numbered(sql), *params))

    async def _fetchrow(self, sql: str, *params: object) -> Any:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(numbered(sql), *params)

    # ---- writes -----------------------------------------------------------------------------

    async def put_user(self, user: User) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET name = $2",
                user.id,
                user.name,
            )

    async def put_deal(self, deal: Deal) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO deals VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET body = $2",
                deal.id,
                deal.model_dump_json(),
            )

    async def put_buyer(self, buyer: BuyerProfile) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO buyers VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET body = $2",
                buyer.id,
                buyer.model_dump_json(),
            )

    async def put_membership(self, membership: Membership) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO memberships VALUES ($1, $2, $3) "
                "ON CONFLICT (deal_id, user_id) DO UPDATE SET role = $3",
                membership.deal_id,
                membership.user_id,
                membership.role.value,
            )

    async def put_document(self, meta: DocumentMeta, pages: Sequence[str]) -> None:
        if len(pages) != meta.n_pages:
            raise ValueError(f"{meta.id}: n_pages={meta.n_pages} but {len(pages)} pages given")
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM chunks WHERE document_id = $1", meta.id)
            await conn.execute("DELETE FROM pages WHERE document_id = $1", meta.id)
            await conn.execute(
                "INSERT INTO documents VALUES ($1, $2, $3) "
                "ON CONFLICT (id) DO UPDATE SET deal_id = $2, body = $3",
                meta.id,
                meta.deal_id,
                meta.model_dump_json(exclude={"tier"}),
            )
            await conn.executemany(
                "INSERT INTO pages VALUES ($1, $2, $3)",
                [(meta.id, i + 1, text) for i, text in enumerate(pages)],
            )

    async def put_chunks(self, chunks: Sequence[Chunk]) -> None:
        """Every chunk must be an exact slice of its stored page, so offsets are trustworthy."""
        async with self._pool.acquire() as conn, conn.transaction():
            for chunk in chunks:
                doc = await conn.fetchrow(
                    "SELECT deal_id FROM documents WHERE id = $1", chunk.document_id
                )
                if doc is None:
                    raise ValueError(f"{chunk.id}: unknown document {chunk.document_id}")
                if doc["deal_id"] != chunk.deal_id:
                    raise ValueError(f"{chunk.id}: deal_id differs from its document")
                page = await conn.fetchrow(
                    "SELECT text FROM pages WHERE document_id = $1 AND page = $2",
                    chunk.document_id,
                    chunk.page,
                )
                if page is None:
                    raise ValueError(f"{chunk.id}: page {chunk.page} does not exist")
                if page["text"][chunk.char_start : chunk.char_end] != chunk.text:
                    raise ValueError(f"{chunk.id}: text is not the page slice at its offsets")
            await conn.executemany(
                f"INSERT INTO chunks ({_CHUNK_COLUMNS}) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) "
                "ON CONFLICT (id) DO UPDATE SET document_id = $2, deal_id = $3, entity_id = $4, "
                "page = $5, char_start = $6, char_end = $7, text = $8, kind = $9, "
                "doc_type = $10, published_on = $11",
                [
                    (
                        c.id,
                        c.document_id,
                        c.deal_id,
                        c.entity_id,
                        c.page,
                        c.char_start,
                        c.char_end,
                        c.text,
                        c.kind,
                        c.doc_type.value,
                        c.published_on.isoformat() if c.published_on else None,
                    )
                    for c in chunks
                ],
            )

    # ---- reads (access predicate inside every query) ---------------------------------------

    async def candidates(
        self,
        access: AccessContext,
        *,
        deal_id: str | None,
        doc_types: Sequence[DocType] | None = None,
    ) -> list[Chunk]:
        acc_sql, acc_params = access_clause(access)
        scope_sql, scope_params = scope_clause(deal_id)
        sql = f"SELECT {_CHUNK_COLUMNS} FROM chunks WHERE {_clause(acc_sql)} AND {scope_sql}"
        params: list[object] = [*acc_params, *scope_params]
        if doc_types is not None:
            marks = ",".join("?" for _ in doc_types)
            sql += f" AND doc_type IN ({marks})" if doc_types else " AND FALSE"
            params.extend(t.value for t in doc_types)
        sql += " ORDER BY id"
        return [_chunk(r) for r in await self._fetch(sql, *params)]

    async def get_chunk(self, chunk_id: str, access: AccessContext) -> Chunk | None:
        acc_sql, acc_params = access_clause(access)
        row = await self._fetchrow(
            f"SELECT {_CHUNK_COLUMNS} FROM chunks WHERE id = ? AND {_clause(acc_sql)}",
            chunk_id,
            *acc_params,
        )
        return _chunk(row) if row else None

    async def get_page(self, document_id: str, page: int, access: AccessContext) -> str | None:
        acc_sql, acc_params = access_clause(access, "d.deal_id")
        row = await self._fetchrow(
            "SELECT p.text FROM pages p JOIN documents d ON d.id = p.document_id "
            f"WHERE p.document_id = ? AND p.page = ? AND {_clause(acc_sql)}",
            document_id,
            page,
            *acc_params,
        )
        return str(row["text"]) if row else None

    async def get_document(self, document_id: str, access: AccessContext) -> DocumentMeta | None:
        acc_sql, acc_params = access_clause(access)
        row = await self._fetchrow(
            f"SELECT body FROM documents WHERE id = ? AND {_clause(acc_sql)}",
            document_id,
            *acc_params,
        )
        return DocumentMeta.model_validate_json(row["body"]) if row else None

    async def list_documents(
        self, access: AccessContext, deal_id: str | None
    ) -> list[DocumentMeta]:
        acc_sql, acc_params = access_clause(access)
        scope_sql, scope_params = scope_clause(deal_id)
        rows = await self._fetch(
            f"SELECT body FROM documents WHERE {_clause(acc_sql)} AND {scope_sql} ORDER BY id",
            *acc_params,
            *scope_params,
        )
        return [DocumentMeta.model_validate_json(r["body"]) for r in rows]

    async def get_deal(self, deal_id: str, access: AccessContext) -> Deal | None:
        if deal_id not in access.allowed_deal_ids:
            return None
        row = await self._fetchrow("SELECT body FROM deals WHERE id = ?", deal_id)
        return Deal.model_validate_json(row["body"]) if row else None

    async def list_deals(self, access: AccessContext) -> list[Deal]:
        allowed = sorted(access.allowed_deal_ids)
        if not allowed:
            return []
        marks = ",".join("?" for _ in allowed)
        rows = await self._fetch(
            f"SELECT body FROM deals WHERE id IN ({marks}) ORDER BY id", *allowed
        )
        return [Deal.model_validate_json(r["body"]) for r in rows]

    async def access_for(self, user_id: str) -> AccessContext:
        if await self._fetchrow("SELECT 1 FROM users WHERE id = ?", user_id) is None:
            raise UnknownUserError(user_id)
        rows = await self._fetch("SELECT deal_id FROM memberships WHERE user_id = ?", user_id)
        return AccessContext(
            user_id=user_id, allowed_deal_ids=frozenset(r["deal_id"] for r in rows)
        )

    async def role_in(self, deal_id: str, user_id: str) -> Role | None:
        row = await self._fetchrow(
            "SELECT role FROM memberships WHERE deal_id = ? AND user_id = ?", deal_id, user_id
        )
        return Role(row["role"]) if row is not None else None

    async def list_users(self) -> list[User]:
        rows = await self._fetch("SELECT id, name FROM users ORDER BY id")
        return [User(id=r["id"], name=r["name"]) for r in rows]

    async def list_buyers(self) -> list[BuyerProfile]:
        rows = await self._fetch("SELECT body FROM buyers ORDER BY id")
        return [BuyerProfile.model_validate_json(r["body"]) for r in rows]
