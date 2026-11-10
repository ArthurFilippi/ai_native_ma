"""Google Gemini over `httpx` (REST `generateContent`, structured output).

The output schema travels as `generationConfig.responseSchema` (the OpenAPI subset Gemini
accepts), not as text in the prompt, so the model is constrained by the API. The default model is
`gemini-2.5-flash`; set `LLM_MODEL` (or `JUDGE_MODEL` for the judge) to change it.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ainma.llm.base import LLMError, Usage
from ainma.llm.providers.http import HttpJsonLLM

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"


_TYPES = {
    "object": "OBJECT",
    "array": "ARRAY",
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
}
_KEPT = ("description", "enum", "format", "minimum", "maximum", "minItems", "maxItems")


def to_gemini_schema(json_schema: dict[str, Any]) -> dict[str, Any]:
    """A pydantic JSON schema turned into Gemini's `responseSchema` subset.

    `$ref` is inlined from `$defs`, `title` and `default` are dropped, `anyOf [X, null]` becomes
    `X` with `nullable`, `const` becomes a one value enum, `date` strings keep their format.
    """
    defs: dict[str, Any] = json_schema.get("$defs", {})

    def convert(node: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in node:
            return convert(defs[node["$ref"].rsplit("/", 1)[-1]])
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            merged: dict[str, Any] = convert(options[0]) if options else {"type": "STRING"}
            if len(options) < len(node["anyOf"]):
                merged["nullable"] = True
            return merged
        out: dict[str, Any] = {}
        kind = node.get("type")
        if "const" in node:
            out["type"] = "STRING"
            out["enum"] = [str(node["const"])]
            return out
        if kind is None and "enum" in node:
            kind = "string"
        out["type"] = _TYPES.get(str(kind), "STRING")
        for key in _KEPT:
            if key in node:
                out[key] = node[key]
        if (
            out["type"] == "STRING"
            and "format" in out
            and out["format"] not in ("date-time", "enum")
        ):
            out.pop("format")
        if "enum" in out:
            out["enum"] = [str(v) for v in out["enum"]]
        if kind == "object":
            props = node.get("properties", {})
            out["properties"] = {name: convert(value) for name, value in props.items()}
            if node.get("required"):
                out["required"] = list(node["required"])
        if kind == "array":
            out["items"] = convert(node.get("items", {"type": "string"}))
        return out

    return convert(json_schema)


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
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": to_gemini_schema(json_schema),
                "temperature": 0.0,
            },
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
