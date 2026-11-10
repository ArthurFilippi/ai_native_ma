"""Clicks to verify: one follow-up request turns a citation into the highlighted passage."""

from __future__ import annotations

import sys
import types
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from ainma.contracts import Answer, Citation, DocType, SourceTier
from tests.fixtures.tiny import tiny_documents
from tests.integration.conftest import as_user

QUOTE = "EUR 182.4 million"


def _cim_page_two() -> str:
    return next(d.pages[1] for d in tiny_documents() if d.meta.id == "doc_cim")


@pytest.fixture
def cited_answer(monkeypatch: pytest.MonkeyPatch) -> Answer:
    """A pipeline stand-in that cites the tiny corpus with page offsets, as core does."""
    start = _cim_page_two().index(QUOTE)
    citation = Citation(
        chunk_id="doc_cim_p2_00",
        document_id="doc_cim",
        doc_title="Project Aurora, Confidential Information Memorandum",
        doc_type=DocType.DEAL_DOCUMENT,
        tier=SourceTier.T2,
        page=2,
        char_start=start,
        char_end=start + len(QUOTE),
        quote=QUOTE,
    )
    answer = Answer.model_validate(
        {
            "id": "ans_x",
            "deal_id": "deal_aurora",
            "user_id": "u_analyst",
            "question": "revenue",
            "summary": "s",
            "claims": [
                {
                    "id": "c1",
                    "text": "Revenue was EUR 182.4 million.",
                    "status": "sourced",
                    "citations": [citation.model_dump(mode="json")],
                }
            ],
            "trace": {"provider": "mock", "model": "mock"},
        }
    )
    module = types.ModuleType("ainma.pipeline")

    async def ask(question: str, **kwargs: Any) -> Answer:
        return answer

    module.ask = ask  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ainma.pipeline", module)
    return answer


@pytest.fixture
async def counting_client(app: FastAPI) -> AsyncIterator[tuple[httpx.AsyncClient, list[str]]]:
    seen: list[str] = []

    async def record(request: httpx.Request) -> None:
        seen.append(request.url.path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", event_hooks={"request": [record]}
    ) as http:
        yield http, seen


async def test_one_follow_up_request_shows_the_highlighted_span(
    counting_client: tuple[httpx.AsyncClient, list[str]], cited_answer: Answer
) -> None:
    client, seen = counting_client
    headers = as_user("u_analyst")
    asked = await client.post(
        "/deals/deal_aurora/ask", json={"question": "revenue"}, headers=headers
    )
    citation = Answer.model_validate(asked.json()).claims[0].citations[0]

    seen.clear()
    passage = await client.get(f"/passages/{citation.chunk_id}?page=true", headers=headers)
    body = passage.json()

    assert seen == ["/passages/doc_cim_p2_00"], "verifying a claim costs exactly one request"
    page_text: str = body["page_text"]
    start, end = body["highlight_start"], body["highlight_end"]
    assert page_text[start:end] == body["chunk"]["text"]
    assert start <= citation.char_start < citation.char_end <= end
    assert page_text[citation.char_start : citation.char_end] == citation.quote
