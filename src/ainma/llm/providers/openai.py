"""OpenAI chat completions over `httpx` (JSON mode)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from ainma.llm.base import LLMError, Usage
from ainma.llm.providers.http import HttpJsonLLM, with_schema

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
OPENAI_BASE_URL = "https://api.openai.com"


class OpenAILLM(HttpJsonLLM):
    provider = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_OPENAI_MODEL,
        *,
        base_url: str = OPENAI_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        **options: Any,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model or DEFAULT_OPENAI_MODEL,
            base_url=base_url,
            transport=transport,
            **options,
        )

    async def _raw(
        self, *, system: str, user: str, json_schema: dict[str, Any], stage: str
    ) -> tuple[str, Usage]:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": with_schema(system, json_schema)},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        started = time.perf_counter()
        payload = await self._post(
            "/v1/chat/completions",
            {"authorization": f"Bearer {self._api_key}", "content-type": "application/json"},
            body,
        )
        latency = (time.perf_counter() - started) * 1000.0
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMError("openai: response has no message content") from error
        if not isinstance(text, str):
            raise LLMError("openai: message content is not text")
        usage = payload.get("usage", {})
        return text, self._usage(
            int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)), latency
        )
