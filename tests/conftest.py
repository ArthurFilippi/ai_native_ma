from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from ainma.store import SqliteStore, Store
from tests.fixtures.tiny import load_tiny

FIXTURES = Path(__file__).parent / "fixtures"


def load_payload(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


PG_URL = os.environ.get("AINMA_TEST_DATABASE_URL", "")


async def _fresh_postgres() -> Store:
    """A Postgres store on an empty schema (AINMA_TEST_DATABASE_URL, a throwaway database)."""
    import asyncpg

    from ainma.store.postgres import PostgresStore

    conn = await asyncpg.connect(PG_URL)
    try:
        await conn.execute(
            "DROP TABLE IF EXISTS chunks, pages, documents, memberships, buyers, deals, users"
        )
    finally:
        await conn.close()
    return await PostgresStore.open(PG_URL)


@pytest.fixture(params=["sqlite", "postgres"])
async def any_store(request: pytest.FixtureRequest) -> AsyncIterator[Store]:
    """The tiny corpus in each backend; the Postgres run needs AINMA_TEST_DATABASE_URL."""
    if request.param == "postgres":
        if not PG_URL:
            pytest.skip("set AINMA_TEST_DATABASE_URL to run the Postgres store tests")
        store: Store = await _fresh_postgres()
    else:
        store = await SqliteStore.open(":memory:")
    await load_tiny(store)
    yield store
    await store.close()


@pytest.fixture
async def tiny_store() -> AsyncIterator[SqliteStore]:
    store = await SqliteStore.open(":memory:")
    await load_tiny(store)
    yield store
    await store.close()
