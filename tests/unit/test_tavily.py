"""Live news connector on a recorded response: no real endpoint is called (D99)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from ainma.connectors.run import run_live_search
from ainma.connectors.tavily import LiveSearchUnavailable, TavilyNewsConnector
from ainma.store import SqliteStore

RECORDED = Path(__file__).resolve().parents[1] / "fixtures_core" / "recorded" / "tavily_news.json"


def _transport(status: int = 200) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=json.loads(RECORDED.read_text("utf-8")))

    return httpx.MockTransport(handler), seen


async def test_items_are_live_dated_and_filtered() -> None:
    transport, seen = _transport()
    connector = TavilyNewsConnector("tvly-secret", transport=transport, today=date(2025, 11, 10))
    query = "industrial components acquisition"
    items = await connector.fetch(entity=query, since=date(2025, 1, 1))
    assert [i.published_on for i in items] == [date(2025, 11, 4), date(2025, 10, 28)]
    assert all(not i.simulated and i.connector == "tavily" for i in items)
    body = json.loads(seen[0].content)
    assert body["topic"] == "news" and body["query"] == query
    assert seen[0].headers["authorization"] == "Bearer tvly-secret"
    assert "tvly-secret" not in str(seen[0].url) and "tvly-secret" not in seen[0].content.decode()


async def test_no_key_and_failures_are_said_not_mocked() -> None:
    with pytest.raises(LiveSearchUnavailable, match="TAVILY_API_KEY"):
        TavilyNewsConnector("")
    transport, _ = _transport(status=401)
    with pytest.raises(LiveSearchUnavailable, match="HTTP 401"):
        await TavilyNewsConnector("k", transport=transport).fetch(entity="q", since=date.min)


async def test_live_items_are_filed_as_web_press_articles(tiny_store: SqliteStore) -> None:
    transport, _ = _transport()
    access = await tiny_store.access_for("u_lead")
    docs = await run_live_search(
        "deal_aurora",
        "industrial components",
        store=tiny_store,
        access=access,
        connector=TavilyNewsConnector("k", transport=transport, today=date(2025, 11, 10)),
    )
    assert len(docs) == 3  # the dated old item is kept when no `since` is given
    assert all(d.origin == "web" and not d.synthetic and d.deal_id == "deal_aurora" for d in docs)
    outsider = await tiny_store.access_for("u_outsider")
    with pytest.raises(LookupError):
        await run_live_search(
            "deal_aurora", "q", store=tiny_store, access=outsider,
            connector=TavilyNewsConnector("k", transport=transport),
        )  # fmt: skip
