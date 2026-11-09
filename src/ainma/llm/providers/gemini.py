"""Google Gemini over `httpx` (REST `generateContent`, JSON mode).

The default model is a Flash class model; set `LLM_MODEL` to change it.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ainma.llm.base import LLMError, Usage
from ainma.llm.providers.http import HttpJsonLLM, with_schema

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"


class GeminiLLM(HttpJsonLLM):
    provider = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_GEMINI_MODEL,
        *,
        base_url: str = GEMINI_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        **options: Any,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model or DEFAULT_GEMINI_MODEL,
            base_url=base_url,
            transport=transport,
            **options,
        )

    async def _raw(
        self, *, system: str, user: str, json_schema: dict[str, Any], stage: str
    ) -> tuple[str, Usage]:
        body = {
            "systemInstruction": {"parts": [{"text": with_schema(system, json_schema)}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0},
        }
        started = time.perf_counter()
        payload = await self._post(
            f"/v1beta/models/{self.model}:generateContent",
            {"x-goog-api-key": self._api_key, "content-type": "application/json"},
            body,
        )
        latency = (time.perf_counter() - started) * 1000.0
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as error:
            reason = (payload.get("promptFeedback") or {}).get("blockReason", "no candidate")
            raise LLMError(f"gemini: no usable candidate ({reason})") from error
        meta = payload.get("usageMetadata", {})
        output_tokens = int(meta.get("candidatesTokenCount", 0)) + int(
            meta.get("thoughtsTokenCount", 0)
        )
        return text, self._usage(int(meta.get("promptTokenCount", 0)), output_tokens, latency)
