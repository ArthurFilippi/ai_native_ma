"""SQLite store: zero infrastructure default. Blocking calls run in a worker thread."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import TypeVar

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
from ainma.store.access import access_clause, scope_clause
from ainma.store.base import UnknownUserError

R = TypeVar("R")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS deals (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS buyers (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memberships (
  deal_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL,
  PRIMARY KEY (deal_id, user_id));
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, deal_id TEXT, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pages (
  document_id TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL,
  PRIMARY KEY (document_id, page));
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, deal_id TEXT, entity_id TEXT,
  page INTEGER NOT NULL, char_start INTEGER NOT NULL, char_end INTEGER NOT NULL,
  text TEXT NOT NULL, kind TEXT NOT NULL, doc_type TEXT NOT NULL, published_on TEXT);
CREATE INDEX IF NOT EXISTS chunks_deal ON chunks (deal_id);
CREATE INDEX IF NOT EXISTS documents_deal ON documents (deal_id);
"""

_CHUNK_COLUMNS = (
    "id, document_id, deal_id, entity_id, page, char_start, char_end, text, kind, "
    "doc_type, published_on"
)


def _chunk_from_row(row: sqlite3.Row) -> Chunk:
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


class SqliteStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, path: str | Path = ":memory:") -> SqliteStore:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)

        def connect() -> sqlite3.Connection:
            conn = sqlite3.connect(str(path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            return conn

        return cls(await asyncio.to_thread(connect))

    async def _run(self, fn: Callable[[sqlite3.Connection], R]) -> R:
        async with self._lock:
            return await asyncio.to_thread(fn, self._conn)

    async def close(self) -> None:
        await self._run(lambda conn: conn.close())

    # ---- writes -----------------------------------------------------------------------------

    async def put_user(self, user: User) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute("INSERT OR REPLACE INTO users VALUES (?, ?)", (user.id, user.name))
            conn.commit()

        await self._run(op)

    async def put_deal(self, deal: Deal) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT OR REPLACE INTO deals VALUES (?, ?)", (deal.id, deal.model_dump_json())
            )
            conn.commit()

        await self._run(op)

    async def put_buyer(self, buyer: BuyerProfile) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT OR REPLACE INTO buyers VALUES (?, ?)", (buyer.id, buyer.model_dump_json())
            )
            conn.commit()

        await self._run(op)

    async def put_membership(self, membership: Membership) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT OR REPLACE INTO memberships VALUES (?, ?, ?)",
                (membership.deal_id, membership.user_id, membership.role.value),
            )
            conn.commit()

        await self._run(op)

    async def put_document(self, meta: DocumentMeta, pages: Sequence[str]) -> None:
        if len(pages) != meta.n_pages:
            raise ValueError(f"{meta.id}: n_pages={meta.n_pages} but {len(pages)} pages given")

        def op(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM pages WHERE document_id = ?", (meta.id,))
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (meta.id,))
            conn.execute(
                "INSERT OR REPLACE INTO documents VALUES (?, ?, ?)",
                (meta.id, meta.deal_id, meta.model_dump_json(exclude={"tier"})),
            )
            conn.executemany(
                "INSERT INTO pages VALUES (?, ?, ?)",
                [(meta.id, i + 1, text) for i, text in enumerate(pages)],
            )
            conn.commit()

        await self._run(op)

    async def put_chunks(self, chunks: Sequence[Chunk]) -> None:
        """Every chunk must be an exact slice of its stored page, so offsets are trustworthy."""

        def op(conn: sqlite3.Connection) -> None:
            for chunk in chunks:
                doc = conn.execute(
                    "SELECT deal_id FROM documents WHERE id = ?", (chunk.document_id,)
                ).fetchone()
                if doc is None:
                    raise ValueError(f"{chunk.id}: unknown document {chunk.document_id}")
                if doc["deal_id"] != chunk.deal_id:
                    raise ValueError(f"{chunk.id}: deal_id differs from its document")
                page = conn.execute(
                    "SELECT text FROM pages WHERE document_id = ? AND page = ?",
                    (chunk.document_id, chunk.page),
                ).fetchone()
                if page is None:
                    raise ValueError(f"{chunk.id}: page {chunk.page} does not exist")
                if page["text"][chunk.char_start : chunk.char_end] != chunk.text:
                    raise ValueError(f"{chunk.id}: text is not the page slice at its offsets")
            conn.executemany(
                f"INSERT OR REPLACE INTO chunks ({_CHUNK_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
            conn.commit()

        await self._run(op)

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
        sql = f"SELECT {_CHUNK_COLUMNS} FROM chunks WHERE {acc_sql} AND {scope_sql}"
        params: list[object] = [*acc_params, *scope_params]
        if doc_types is not None:
            marks = ",".join("?" for _ in doc_types)
            sql += f" AND doc_type IN ({marks})" if doc_types else " AND 0"
            params.extend(t.value for t in doc_types)
        sql += " ORDER BY id"

        def op(conn: sqlite3.Connection) -> list[Chunk]:
            return [_chunk_from_row(r) for r in conn.execute(sql, params).fetchall()]

        return await self._run(op)

    async def get_chunk(self, chunk_id: str, access: AccessContext) -> Chunk | None:
        acc_sql, acc_params = access_clause(access)
        sql = f"SELECT {_CHUNK_COLUMNS} FROM chunks WHERE id = ? AND {acc_sql}"

        def op(conn: sqlite3.Connection) -> Chunk | None:
            row = conn.execute(sql, [chunk_id, *acc_params]).fetchone()
            return _chunk_from_row(row) if row else None

        return await self._run(op)

    async def get_page(self, document_id: str, page: int, access: AccessContext) -> str | None:
        acc_sql, acc_params = access_clause(access, "d.deal_id")
        sql = (
            "SELECT p.text FROM pages p JOIN documents d ON d.id = p.document_id "
            f"WHERE p.document_id = ? AND p.page = ? AND {acc_sql}"
        )

        def op(conn: sqlite3.Connection) -> str | None:
            row = conn.execute(sql, [document_id, page, *acc_params]).fetchone()
            return str(row["text"]) if row else None

        return await self._run(op)

    async def get_document(self, document_id: str, access: AccessContext) -> DocumentMeta | None:
        acc_sql, acc_params = access_clause(access)
        sql = f"SELECT body FROM documents WHERE id = ? AND {acc_sql}"

        def op(conn: sqlite3.Connection) -> DocumentMeta | None:
            row = conn.execute(sql, [document_id, *acc_params]).fetchone()
            return DocumentMeta.model_validate_json(row["body"]) if row else None

        return await self._run(op)

    async def list_documents(
        self, access: AccessContext, deal_id: str | None
    ) -> list[DocumentMeta]:
        acc_sql, acc_params = access_clause(access)
        scope_sql, scope_params = scope_clause(deal_id)
        sql = f"SELECT body FROM documents WHERE {acc_sql} AND {scope_sql} ORDER BY id"

        def op(conn: sqlite3.Connection) -> list[DocumentMeta]:
            rows = conn.execute(sql, [*acc_params, *scope_params]).fetchall()
            return [DocumentMeta.model_validate_json(r["body"]) for r in rows]

        return await self._run(op)

    async def get_deal(self, deal_id: str, access: AccessContext) -> Deal | None:
        if deal_id not in access.allowed_deal_ids:
            return None

        def op(conn: sqlite3.Connection) -> Deal | None:
            row = conn.execute("SELECT body FROM deals WHERE id = ?", (deal_id,)).fetchone()
            return Deal.model_validate_json(row["body"]) if row else None

        return await self._run(op)

    async def list_deals(self, access: AccessContext) -> list[Deal]:
        allowed = sorted(access.allowed_deal_ids)
        if not allowed:
            return []
        marks = ",".join("?" for _ in allowed)

        def op(conn: sqlite3.Connection) -> list[Deal]:
            rows = conn.execute(
                f"SELECT body FROM deals WHERE id IN ({marks}) ORDER BY id", allowed
            ).fetchall()
            return [Deal.model_validate_json(r["body"]) for r in rows]

        return await self._run(op)

    async def access_for(self, user_id: str) -> AccessContext:
        def op(conn: sqlite3.Connection) -> AccessContext:
            if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                raise UnknownUserError(user_id)
            rows = conn.execute(
                "SELECT deal_id FROM memberships WHERE user_id = ?", (user_id,)
            ).fetchall()
            return AccessContext(
                user_id=user_id, allowed_deal_ids=frozenset(r["deal_id"] for r in rows)
            )

        return await self._run(op)

    async def list_users(self) -> list[User]:
        def op(conn: sqlite3.Connection) -> list[User]:
            rows = conn.execute("SELECT id, name FROM users ORDER BY id").fetchall()
            return [User(id=r["id"], name=r["name"]) for r in rows]

        return await self._run(op)

    async def list_buyers(self) -> list[BuyerProfile]:
        def op(conn: sqlite3.Connection) -> list[BuyerProfile]:
            rows = conn.execute("SELECT body FROM buyers ORDER BY id").fetchall()
            return [BuyerProfile.model_validate_json(r["body"]) for r in rows]

        return await self._run(op)
