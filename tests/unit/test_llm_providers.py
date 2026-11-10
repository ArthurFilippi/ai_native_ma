"""Live providers on recorded response bodies only: no real endpoint is ever called."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from ainma.llm import FallbackLLM, LLMError, build_llm
from ainma.llm.providers import build_live_llm
from ainma.llm.providers.gemini import DEFAULT_GEMINI_MODEL, GeminiLLM
from ainma.llm.providers.http import cost_usd, load_prices
from ainma.llm.providers.openai import DEFAULT_OPENAI_MODEL, OpenAILLM
from ainma.llm.tasks import TASK_JUDGE
from ainma.pipeline.schemas import JudgeResult
from ainma.settings import Settings

RECORDED = Path(__file__).resolve().parents[1] / "fixtures_core" / "recorded"
PRICES: dict[str, Any] = {
    "models": {
        "gemini-2.5-flash": {"input_per_mtok": 0.5, "output_per_mtok": 2.0},
        "gpt-4o-mini": {"input_per_mtok": None, "output_per_mtok": None},
    }
}
USER = json.dumps(
    {"claim": "Revenue was EUR 182.4 million.", "quotes": ["EUR 182.4 million"], "context": ""}
)


def recorded(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((RECORDED / name).read_text(encoding="utf-8"))
    return data


class Replay:
    """httpx transport that answers with a queue of (status, recorded file) and keeps requests."""

    def __init__(self, *responses: tuple[int, str]) -> None:
        self._queue = list(responses)
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            status, name = self._queue.pop(0) if len(self._queue) > 1 else self._queue[0]
            return httpx.Response(status, json=recorded(name))

        return httpx.MockTransport(handler)


async def _judge(llm: Any) -> Any:
    return await llm.complete_json(
        task=TASK_JUDGE, system="Judge.", user=USER, schema=JudgeResult, stage="verify"
    )


async def test_gemini_parses_json_mode_response_and_usage() -> None:
    replay = Replay((200, "gemini_ok.json"))
    llm = GeminiLLM("key-123", transport=replay.transport(), prices=PRICES, backoff_s=0)
    result, usage = await _judge(llm)
    assert result.label == "supported"
    assert (usage.provider, usage.model) == ("gemini", DEFAULT_GEMINI_MODEL)
    assert usage.input_tokens == 812 and usage.output_tokens == 63  # 23 answer + 40 thinking
    assert usage.cost_usd == pytest.approx((812 * 0.5 + 63 * 2.0) / 1e6)
    request = replay.requests[0]
    body = json.loads(request.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert "label" in body["generationConfig"]["responseSchema"]["properties"]
    assert request.headers["x-goog-api-key"] == "key-123"
    assert "key-123" not in str(request.url)
    assert request.url.path.endswith(f"/models/{DEFAULT_GEMINI_MODEL}:generateContent")


async def test_validation_failure_retries_once_with_the_error_and_merges_usage() -> None:
    replay = Replay((200, "gemini_invalid_label.json"), (200, "gemini_ok.json"))
    llm = GeminiLLM("k", transport=replay.transport(), prices=PRICES, backoff_s=0)
    result, usage = await _judge(llm)
    assert result.label == "supported" and len(replay.requests) == 2
    retry_text = json.loads(replay.requests[1].content)["contents"][0]["parts"][0]["text"]
    assert "failed validation" in retry_text
    assert usage.input_tokens == 812 + 800  # both attempts are paid for


async def test_two_invalid_replies_raise_llm_error() -> None:
    replay = Replay((200, "gemini_invalid_label.json"))
    llm = GeminiLLM("k", transport=replay.transport(), backoff_s=0)
    with pytest.raises(LLMError, match="failed validation twice"):
        await _judge(llm)


async def test_gemini_blocked_prompt_is_an_llm_error() -> None:
    llm = GeminiLLM("k", transport=Replay((200, "gemini_blocked.json")).transport(), backoff_s=0)
    with pytest.raises(LLMError, match="SAFETY"):
        await _judge(llm)


async def test_openai_parses_response_usage_and_unknown_price_is_none() -> None:
    replay = Replay((200, "openai_ok.json"))
    llm = OpenAILLM("sk-test", transport=replay.transport(), prices=PRICES, backoff_s=0)
    result, usage = await _judge(llm)
    assert result.label == "supported"
    assert (usage.provider, usage.model) == ("openai", DEFAULT_OPENAI_MODEL)
    assert (usage.input_tokens, usage.output_tokens) == (790, 21)
    assert usage.cost_usd is None  # price is null: never estimated
    body = json.loads(replay.requests[0].content)
    assert body["response_format"] == {"type": "json_object"} and body["temperature"] == 0
    assert replay.requests[0].headers["authorization"] == "Bearer sk-test"
    fenced, _ = await _judge(
        OpenAILLM("k", transport=Replay((200, "openai_fenced.json")).transport(), backoff_s=0)
    )
    assert fenced.label == "supported"  # markdown fences are tolerated


async def test_rate_limit_is_retried_then_succeeds() -> None:
    replay = Replay((429, "openai_rate_limited.json"), (200, "openai_ok.json"))
    llm = OpenAILLM("k", transport=replay.transport(), backoff_s=0)
    result, _ = await _judge(llm)
    assert result.label == "supported" and len(replay.requests) == 2


async def test_unauthorized_is_not_retried_and_never_echoes_the_key() -> None:
    replay = Replay((401, "openai_unauthorized.json"))
    llm = OpenAILLM("sk-secret-value", transport=replay.transport(), backoff_s=0)
    with pytest.raises(LLMError) as raised:
        await _judge(llm)
    assert len(replay.requests) == 1 and "sk-secret-value" not in str(raised.value)


async def test_network_failure_is_an_llm_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network", request=request)

    llm = GeminiLLM("k", transport=httpx.MockTransport(boom), backoff_s=0, max_retries=1)
    with pytest.raises(LLMError, match="ConnectError"):
        await _judge(llm)


def test_missing_key_fails_at_construction() -> None:
    with pytest.raises(LLMError, match="no API key"):
        GeminiLLM("")


def test_price_table_has_null_prices_and_provenance_fields() -> None:
    prices = load_prices()
    assert {"currency", "as_of", "source", "models"} <= set(prices)
    assert all(v["input_per_mtok"] is None for v in prices["models"].values())  # none invented
    assert cost_usd("gemini-2.5-flash", 1000, 1000, prices) is None
    assert cost_usd("unknown-model", 1, 1, PRICES) is None
    assert cost_usd("gemini-2.5-flash", 1_000_000, 0, PRICES) == pytest.approx(0.5)


async def test_live_factory_falls_back_to_the_mock_visibly_and_caches(tmp_path: Path) -> None:
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="k",
        llm_cache_dir=tmp_path,
        llm_allow_mock_fallback=True,  # opt in only (D88)
        _env_file=None,
    )
    failing = Replay((500, "openai_rate_limited.json"))
    llm = build_live_llm(settings, transport=failing.transport())
    assert isinstance(llm, FallbackLLM) and llm.provider == "gemini"
    result, usage = await _judge(llm)
    assert result.label in {"supported", "partial", "unsupported"}  # the mock answered
    assert usage.fallback_from == "gemini" and usage.provider == "mock"
    assert len(failing.requests) == 3  # one try and two retries

    working = Replay((200, "gemini_ok.json"))
    cached = build_live_llm(settings, transport=working.transport())
    first, first_usage = await _judge(cached)
    second, second_usage = await _judge(cached)
    assert first == second and len(working.requests) == 1
    assert not first_usage.cached and second_usage.cached and second_usage.fallback_from is None


def test_live_factory_rejects_the_mock_and_missing_keys(tmp_path: Path) -> None:
    with pytest.raises(LLMError, match="not a live provider"):
        build_live_llm(Settings(llm_provider="mock", _env_file=None))
    with pytest.raises(LLMError, match="no API key"):
        build_live_llm(
            Settings(
                llm_provider="openai", openai_api_key="", llm_cache_dir=tmp_path, _env_file=None
            )
        )


def test_model_comes_from_settings_with_a_documented_default(tmp_path: Path) -> None:
    named = Settings(
        llm_provider="openai", openai_api_key="k", llm_model="my-model", llm_cache_dir=tmp_path,
        _env_file=None,
    )  # fmt: skip
    assert build_live_llm(named).model == "my-model"
    default = Settings(
        llm_provider="gemini", gemini_api_key="k", llm_cache_dir=tmp_path, _env_file=None
    )
    assert build_live_llm(default).model == DEFAULT_GEMINI_MODEL
    assert build_llm(Settings(_env_file=None)).provider == "mock"
