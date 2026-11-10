"""The API shares one retrieval engine across questions and answers 503 when the live model
fails, instead of a mock answer presented as a model answer."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI

from ainma.api import create_app
from ainma.llm import LLMError, build_mock_llm
from ainma.runtime import Runtime
from ainma.settings import Settings
from ainma.store import SqliteStore
from tests.integration.conftest import as_user


class Broken:
    provider, model = "gemini", "gemini-2.5-flash"

    async def complete_json(self, **_: Any) -> Any:
        raise LLMError("gemini: request failed (HTTP 503)")


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_questions_reuse_one_fitted_index(tiny_store: SqliteStore) -> None:
    runtime = Runtime(settings=Settings(_env_file=None), store=tiny_store, llm=build_mock_llm())
    async with _client(create_app(runtime)) as client:
        for question in ("What was FY2024 revenue?", "What was FY2023 revenue?"):
            response = await client.post(
                "/deals/deal_aurora/ask", json={"question": question}, headers=as_user("u_analyst")
            )
            assert response.status_code == 200
    assert runtime.engine.fits == 1


async def test_live_model_failure_is_a_clear_503(tiny_store: SqliteStore) -> None:
    runtime = Runtime(settings=Settings(_env_file=None), store=tiny_store, llm=Broken())
    async with _client(create_app(runtime)) as client:
        response = await client.post(
            "/deals/deal_aurora/ask",
            json={"question": "What was FY2024 revenue?"},
            headers=as_user("u_analyst"),
        )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "gemini" in detail and "no answer was produced" in detail
