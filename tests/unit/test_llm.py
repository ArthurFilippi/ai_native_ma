from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from ainma.llm import (
    CachedLLM,
    DiskCache,
    FallbackLLM,
    LLMError,
    MockLLM,
    RawJsonLLM,
    Usage,
    build_llm,
)
from ainma.llm.cache import cache_key
from ainma.settings import Settings


class Echo(BaseModel):
    text: str


def _echo(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    return schema(text=user.upper())


async def test_mock_is_deterministic_and_offline() -> None:
    llm = MockLLM({"echo": _echo})
    first, usage = await llm.complete_json(
        task="echo", system="s", user="a", schema=Echo, stage="t"
    )
    second, _ = await llm.complete_json(task="echo", system="s", user="a", schema=Echo, stage="t")
    assert first == second == Echo(text="A")
    assert usage.provider == "mock" and usage.cost_usd is None


async def test_mock_fails_loudly_on_unknown_task() -> None:
    with pytest.raises(LLMError, match="not implemented"):
        await MockLLM({}).complete_json(task="nope", system="", user="", schema=Echo, stage="t")


async def test_disk_cache_hit_skips_the_provider(tmp_path: Path) -> None:
    calls = 0

    def counting(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
        nonlocal calls
        calls += 1
        return schema(text=user)

    llm = CachedLLM(MockLLM({"echo": counting}), DiskCache(tmp_path))
    a, usage_a = await llm.complete_json(task="echo", system="s", user="x", schema=Echo, stage="t")
    b, usage_b = await llm.complete_json(task="echo", system="s", user="x", schema=Echo, stage="t")
    assert a == b and calls == 1
    assert not usage_a.cached and usage_b.cached


def test_cache_key_depends_on_every_component() -> None:
    base = {"provider": "p", "model": "m", "task": "t", "system": "s", "user": "u", "schema": "S"}
    keys = {cache_key(**base)}
    for field in base:
        keys.add(cache_key(**{**base, field: base[field] + "x"}))
    assert len(keys) == len(base) + 1


class _Flaky(RawJsonLLM):
    provider = "flaky"
    model = "flaky-1"

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    async def _raw(self, *, system: str, user: str, json_schema: dict, stage: str):  # type: ignore[no-untyped-def,type-arg]
        self.prompts.append(user)
        return self.replies.pop(0), Usage(provider=self.provider, model=self.model, input_tokens=3)


async def test_validation_retries_once_with_the_error() -> None:
    llm = _Flaky(["not json", '```json\n{"text": "ok"}\n```'])
    parsed, usage = await llm.complete_json(task="t", system="", user="q", schema=Echo, stage="t")
    assert parsed == Echo(text="ok") and usage.input_tokens == 6
    assert "failed validation" in llm.prompts[1]


async def test_validation_gives_up_after_one_retry() -> None:
    llm = _Flaky(["bad", "still bad"])
    with pytest.raises(LLMError, match="twice"):
        await llm.complete_json(task="t", system="", user="q", schema=Echo, stage="t")


async def test_fallback_to_mock_is_never_silent() -> None:
    primary = _Flaky(["bad", "bad"])
    llm = FallbackLLM(primary, MockLLM({"echo": _echo}))
    parsed, usage = await llm.complete_json(
        task="echo", system="", user="z", schema=Echo, stage="t"
    )
    assert parsed == Echo(text="Z")
    assert usage.fallback_from == "flaky" and usage.provider == "mock"


def test_factory_builds_mock_by_default_and_rejects_unwired_providers() -> None:
    assert build_llm(Settings(llm_provider="mock")).provider == "mock"
    with pytest.raises(LLMError):
        build_llm(Settings(llm_provider="gemini"))
