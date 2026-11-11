"""Live news through the Tavily search API (D99).

`TavilyNewsConnector.fetch(entity=<query>)` asks Tavily's news search for recent articles and
returns them as connector items with `simulated = False`. They are filed in the deal space as
press articles (tier 4) with `origin = "web"` and `synthetic = False`, so the UI labels them live
and the ranker treats them like any other press source. The key comes from `TAVILY_API_KEY` and
travels in the `Authorization: Bearer` header; it is never logged. Tests use recorded responses.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from ainma.contracts import ConnectorItem, DocType

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"


class LiveSearchUnavailable(RuntimeError):
    """No key is configured, or the service failed: said to the user, never replaced by a mock."""


def _published(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError):
        return None


class TavilyNewsConnector:
    name = "tavily"
    simulated = False

    def __init__(
        self,
        api_key: str,
        *,
        days: int = 30,
        max_results: int = 8,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 20.0,
        today: date | None = None,
    ) -> None:
        if not api_key:
            raise LiveSearchUnavailable("live search is not configured: set TAVILY_API_KEY")
        self._key = api_key
        self._days = days
        self._max = max_results
        self._transport = transport
        self._timeout = timeout_s
        self._today = today

    async def fetch(self, *, entity: str, since: date) -> list[ConnectorItem]:
        """Recent news for the query `entity`, published on or after `since` when dated."""
        body = {
            "query": entity,
            "topic": "news",
            "days": self._days,
            "max_results": self._max,
            "include_answer": False,
        }
        headers = {"authorization": f"Bearer {self._key}", "content-type": "application/json"}
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = await client.post(TAVILY_URL, json=body, headers=headers)
        except httpx.HTTPError as error:
            raise LiveSearchUnavailable(f"tavily: {type(error).__name__}") from error
        if response.status_code >= 400:
            raise LiveSearchUnavailable(f"tavily: HTTP {response.status_code}")
        payload: dict[str, Any] = response.json()
        retrieved = self._today or date.today()
        items: list[ConnectorItem] = []
        for row in payload.get("results", []):
            title, content = str(row.get("title", "")).strip(), str(row.get("content", "")).strip()
            if not title or not content:
                continue
            published = _published(row.get("published_date"))
            if published is not None and published < since:
                continue
            items.append(
                ConnectorItem(
                    connector=self.name,
                    retrieved_on=retrieved,
                    title=title,
                    url=str(row.get("url")) if row.get("url") else None,
                    published_on=published,
                    doc_type=DocType.PRESS_ARTICLE,
                    text=content,
                    simulated=False,
                )
            )
        logger.info("tavily: %d items for a query of %d characters", len(items), len(entity))
        return items
