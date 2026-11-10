"""Live provider layer on recorded bodies: structured output, Retry-After, concurrency, no silent
mock fallback, a judge model distinct from the writer. No real endpoint is ever called."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from ainma.llm import FallbackLLM, LLMError
from ainma.llm.factory import build_judge_llm
from ainma.llm.providers import build_live_llm
from ainma.llm.providers.gemini import GeminiLLM, to_gemini_schema
from ainma.llm.tasks import TASK_JUDGE, TASK_WRITE
from ainma.pipeline.schemas import JudgeResult, WriteResult
from ainma.settings import Settings
from tests.unit.test_llm_providers import USER, Replay, recorded


async def _judge(llm: Any) -> Any:
    return await llm.complete_json(
        task=TASK_JUDGE, system="Judge.", user=USER, schema=JudgeResult, stage="verify"
    )


def _walk(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, dict):
        out.append(node)
        for value in node.values():
            out.extend(_walk(value))
    elif isinstance(node, list):
        for value in node:
            out.extend(_walk(value))
    return out


def test_gemini_schema_is_the_openapi_subset_without_refs() -> None:
    schema = to_gemini_schema(WriteResult.model_json_schema())
    nodes = _walk(schema)
    assert not any("$ref" in n or "$defs" in n or "title" in n or "anyOf" in n for n in nodes)
    assert schema["type"] == "OBJECT"
    claims = schema["properties"]["claims"]
    assert claims["type"] == "ARRAY" and claims["items"]["type"] == "OBJECT"
    status = claims["items"]["properties"]["status"]
    assert status == {"type": "STRING", "enum": ["sourced", "inferred"]}
    assert "claims" in schema["required"]


async def test_gemini_sends_response_schema_not_a_schema_in_the_prompt() -> None:
    replay = Replay((200, "gemini_ok.json"))
    llm = GeminiLLM("k", transport=replay.transport(), backoff_s=0)
    await _judge(llm)
    body = json.loads(replay.requests[0].content)
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"]["properties"]["label"]["enum"] == [
        "supported",
        "partial",
        "unsupported",
    ]
    assert body["systemInstruction"]["parts"][0]["text"] == "Judge."


async def test_retry_after_header_is_respected() -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, json={"error": "slow"})
        return httpx.Response(200, json=recorded("gemini_ok.json"))

    llm = GeminiLLM("k", transport=httpx.MockTransport(handler), backoff_s=0.5, sleep=fake_sleep)
    result, _ = await _judge(llm)
    assert result.label == "supported"
    assert slept == [7.0]


async def test_retry_after_is_capped() -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"Retry-After": "3600"}, json={})

    llm = GeminiLLM("k", transport=httpx.MockTransport(handler), max_retries=1, sleep=fake_sleep)
    with pytest.raises(LLMError, match="HTTP 503"):
        await _judge(llm)
    assert slept == [llm.max_retry_after_s]


async def test_concurrency_is_limited_per_provider() -> None:
    state = {"now": 0, "peak": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1
        return httpx.Response(200, json=recorded("gemini_ok.json"))

    llm = GeminiLLM("k", transport=httpx.MockTransport(handler), max_concurrency=2)
    await asyncio.gather(*(_judge(llm) for _ in range(6)))
    assert state["peak"] == 2


async def test_live_failure_is_an_error_by_default_not_a_mock_answer(tmp_path: Path) -> None:
    settings = Settings(
        llm_provider="gemini", gemini_api_key="k", llm_cache_dir=tmp_path, _env_file=None
    )
    failing = Replay((500, "openai_rate_limited.json"))
    llm = build_live_llm(settings, transport=failing.transport())
    assert not isinstance(llm, FallbackLLM)
    with pytest.raises(LLMError, match="gemini"):
        await _judge(llm)


async def test_mock_fallback_is_opt_in_and_marked(tmp_path: Path) -> None:
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="k",
        llm_cache_dir=tmp_path,
        llm_allow_mock_fallback=True,
        _env_file=None,
    )
    llm = build_live_llm(settings, transport=Replay((500, "openai_rate_limited.json")).transport())
    assert isinstance(llm, FallbackLLM)
    _, usage = await _judge(llm)
    assert usage.fallback_from == "gemini"


def test_judge_model_is_configured_separately(tmp_path: Path) -> None:
    same = Settings(
        llm_provider="gemini", gemini_api_key="k", llm_cache_dir=tmp_path, _env_file=None
    )
    assert build_judge_llm(same) is None  # no judge setting: the writer judges, and says so
    split = Settings(
        llm_provider="gemini",
        gemini_api_key="k",
        judge_provider="gemini",
        judge_model="gemini-2.5-pro",
        llm_cache_dir=tmp_path,
        _env_file=None,
    )
    judge = build_judge_llm(split)
    assert judge is not None and (judge.provider, judge.model) == ("gemini", "gemini-2.5-pro")
    mock_judge = build_judge_llm(Settings(judge_provider="mock", _env_file=None))
    assert mock_judge is not None and mock_judge.provider == "mock"


def test_write_schema_is_accepted_by_the_converter_for_every_task() -> None:
    from ainma.pipeline.schemas import ExtractFactsResult, UnderstandResult

    for model in (WriteResult, JudgeResult, ExtractFactsResult, UnderstandResult):
        converted = to_gemini_schema(model.model_json_schema())
        assert converted["type"] == "OBJECT"
    assert TASK_WRITE == "write"
