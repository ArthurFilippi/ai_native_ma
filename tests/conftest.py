from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from ainma.store import SqliteStore
from tests.fixtures.tiny import load_tiny

FIXTURES = Path(__file__).parent / "fixtures"


def load_payload(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


@pytest.fixture
async def tiny_store() -> AsyncIterator[SqliteStore]:
    store = await SqliteStore.open(":memory:")
    await load_tiny(store)
    yield store
    await store.close()
