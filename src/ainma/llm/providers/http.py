"""Shared plumbing of the live providers: one POST with retries, usage and price handling."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from ainma.llm.base import LLMError, RawJsonLLM, Usage

logger = logging.getLogger(__name__)

PRICES_PATH = Path(__file__).with_name("prices.json")
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def load_prices() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(PRICES_PATH.read_text(encoding="utf-8"))
    return data


def cost_usd(
    model: str, input_tokens: int, output_tokens: int, prices: dict[str, Any]
) -> float | None:
    """Cost of one call from the price table, or None when the model or a price is unknown."""
    table = prices.get("models", {})
    entry = table.get(model)
    if not entry or entry.get("input_per_mtok") is None or entry.get("output_per_mtok") is None:
        return None
    return float(
        (input_tokens * entry["input_per_mtok"] + output_tokens * entry["output_per_mtok"])
        / 1_000_000
    )


def with_schema(system: str, json_schema: dict[str, Any]) -> str:
    return f"{system}\n\nThe JSON must validate against this schema:\n{json.dumps(json_schema)}"


class HttpJsonLLM(RawJsonLLM):
    """A provider that POSTs JSON. Subclasses build the request and parse the response."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 60.0,
        max_retries: int = 2,
        backoff_s: float = 0.5,
        prices: dict[str, Any] | None = None,
    ) -> None:
        if not api_key:
            raise LLMError(f"{self.provider}: no API key configured")
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._prices = prices if prices is not None else load_prices()

    async def _post(
        self, path: str, headers: dict[str, str], body: dict[str, Any]
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        last = "no attempt"
        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout_s) as client:
            for attempt in range(self._max_retries + 1):
                try:
                    response = await client.post(url, headers=headers, json=body)
                except httpx.HTTPError as error:
                    last = f"{type(error).__name__}"
                else:
                    if response.status_code < 400:
                        try:
                            payload = response.json()
                        except ValueError as error:
                            raise LLMError(f"{self.provider}: response is not JSON") from error
                        if isinstance(payload, dict):
                            return payload
                        raise LLMError(f"{self.provider}: unexpected response shape")
                    last = f"HTTP {response.status_code}: {response.text[:200]}"
                    if response.status_code not in RETRY_STATUSES:
                        break
                if attempt < self._max_retries:
                    await asyncio.sleep(self._backoff_s * (2**attempt))
        raise LLMError(f"{self.provider}: request failed ({last})")

    def _usage(self, input_tokens: int, output_tokens: int, latency_ms: float) -> Usage:
        return Usage(
            provider=self.provider,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd(self.model, input_tokens, output_tokens, self._prices),
            latency_ms=latency_ms,
        )
