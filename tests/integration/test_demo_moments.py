"""The demo moments of the five minute scenario, end to end on the seeded corpus (seed 1234).

Offline, mock provider, no network. Each test is one moment of `ainma.demo.DEMO_SCRIPT`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainma.api import create_app
from ainma.contracts import VALUE_CONTRACT, Answer, ClaimStatus
from ainma.ingest.loader import load_corpus
from ainma.llm import build_mock_llm
from ainma.runtime import Runtime
from ainma.settings import Settings
from ainma.store import SqliteStore
from ainma.synth.generate import generate

DEAL = "deal_aurora"


@pytest.fixture(scope="module")
def seed_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate(1234, tmp_path_factory.mktemp("synthetic"))


@pytest.fixture
async def app(seed_dir: Path) -> AsyncIterator[FastAPI]:
    store = await SqliteStore.open(":memory:")
    await load_corpus(store, seed_dir)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    yield create_app(Runtime(settings=settings, store=store, llm=build_mock_llm()))
    await store.close()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://demo"
    ) as http:
        yield http


def _as(user: str) -> dict[str, str]:
    return {"X-User-Id": user}


async def _ask(client: httpx.AsyncClient, user: str, question: str) -> Answer:
    response = await client.post(
        f"/deals/{DEAL}/ask", json={"question": question}, headers=_as(user)
    )
    assert response.status_code == 200, response.text
    return Answer.model_validate(response.json())


async def test_access_denial(client: httpx.AsyncClient) -> None:
    visible = await client.get("/deals", headers=_as("u_analyst"))
    assert DEAL in [d["id"] for d in visible.json()]
    hidden = await client.get("/deals", headers=_as("u_outsider"))
    assert DEAL not in [d["id"] for d in hidden.json()]
    assert (await client.get(f"/deals/{DEAL}", headers=_as("u_outsider"))).status_code == 404
    ask = await client.post(
        f"/deals/{DEAL}/ask", json={"question": "revenue?"}, headers=_as("u_outsider")
    )
    assert ask.status_code == 404


async def test_source_verification_in_one_click(client: httpx.AsyncClient) -> None:
    answer = await _ask(client, "u_analyst", "What was Aurora's gross margin in FY2024?")
    assert answer.value_contract == VALUE_CONTRACT
    sourced = [c for c in answer.claims if c.status is ClaimStatus.SOURCED]
    assert sourced, "a factual question must yield a sourced claim"
    citation = sourced[0].citations[0]
    one_click = await client.get(
        f"/passages/{citation.chunk_id}", params={"page": "true"}, headers=_as("u_analyst")
    )
    body = one_click.json()
    page = body["page_text"]
    assert page[body["highlight_start"] : body["highlight_end"]] == body["chunk"]["text"]
    assert citation.quote in body["chunk"]["text"]
    assert page[citation.char_start : citation.char_end] == citation.quote
    assert body["document"]["doc_type"] == citation.doc_type.value


async def test_contradiction_is_shown_not_resolved(client: httpx.AsyncClient) -> None:
    answer = await _ask(client, "u_analyst", "What was Aurora's FY2024 revenue?")
    assert answer.contradictions, "CIM and trade press disagree on FY2024 revenue"
    contradiction = answer.contradictions[0]
    assert len(contradiction.sides) >= 2
    tiers = {side.citations[0].tier.value for side in contradiction.sides}
    assert len(tiers) >= 2, "the sides come from sources of different reliability tiers"
    assert "does not pick a winner" in contradiction.note


async def test_abstention_when_the_information_is_absent(client: httpx.AsyncClient) -> None:
    answer = await _ask(client, "u_analyst", "What is the CEO's compensation package?")
    assert answer.abstained
    assert answer.abstention_reason
    assert all(c.status is ClaimStatus.MISSING for c in answer.claims)
    assert not any(c.citations for c in answer.claims)
