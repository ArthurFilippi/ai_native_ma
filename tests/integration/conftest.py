from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from ainma.api import create_app
from ainma.llm import build_mock_llm
from ainma.runtime import Runtime
from ainma.settings import Settings
from ainma.store import SqliteStore


@pytest.fixture
def app(tiny_store: SqliteStore) -> FastAPI:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    return create_app(Runtime(settings=settings, store=tiny_store, llm=build_mock_llm()))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def as_user(user_id: str) -> dict[str, str]:
    return {"X-User-Id": user_id}
