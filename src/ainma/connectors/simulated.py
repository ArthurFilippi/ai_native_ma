"""Simulated news connector: dated fixtures from the generator, served deterministically."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

from ainma.contracts import ConnectorItem
from ainma.truth import NewsFeedItem


class SimulatedNewsConnector:
    """Reads `news/items.json` of a seed directory. Always `simulated = True`: the UI shows it."""

    name = "simulated-news"
    simulated = True

    def __init__(self, seed_dir: Path) -> None:
        self._path = seed_dir / "news" / "items.json"

    async def _items(self) -> list[NewsFeedItem]:
        raw = await asyncio.to_thread(self._path.read_text, encoding="utf-8")
        return [NewsFeedItem.model_validate(item) for item in json.loads(raw)]

    async def entities(self) -> list[str]:
        """Every entity the feed has items for, sorted."""
        return sorted({item.entity for item in await self._items()})

    async def fetch(self, *, entity: str, since: date) -> list[ConnectorItem]:
        """Items about `entity` published on or after `since`, oldest first. An item without a
        publication date is dated by its retrieval date."""
        selected = [
            item
            for item in await self._items()
            if item.entity == entity and (item.published_on or item.retrieved_on) >= since
        ]
        ordered = sorted(selected, key=lambda i: (i.published_on or i.retrieved_on, i.title))
        return [*ordered]
