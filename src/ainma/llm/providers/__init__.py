"""Provider implementations. `build_live_llm` is what `ainma.llm.factory` wires for live keys."""

from __future__ import annotations

import httpx

from ainma.llm.base import LLM, LLMError
from ainma.settings import Settings


def build_live_llm(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    provider_name: str | None = None,
    model: str | None = None,
) -> LLM:
    """`CachedLLM(provider, DiskCache(settings.llm_cache_dir))`.

    A failed call raises `LLMError`. Only with `LLM_ALLOW_MOCK_FALLBACK=true` is the result
    wrapped in `FallbackLLM`, so the mock answers and says so in `Usage.fallback_from` (the
    pipeline then marks the answer `degraded`). `provider_name` and `model` default to
    `settings.llm_provider` and `settings.llm_model` (empty means the provider default); the judge
    passes its own. `transport` lets tests inject recorded responses.
    """
    from ainma.llm.cache import CachedLLM, DiskCache, FallbackLLM
    from ainma.llm.mock import MockLLM
    from ainma.llm.providers.gemini import GeminiLLM
    from ainma.llm.providers.mock_tasks import default_mock_handlers
    from ainma.llm.providers.openai import OpenAILLM

    name = provider_name or settings.llm_provider
    chosen = settings.llm_model if model is None else model
    concurrency, timeout = settings.llm_max_concurrency, settings.llm_timeout_s
    provider: LLM
    if name == "gemini":
        provider = GeminiLLM(
            settings.gemini_api_key,
            chosen,
            transport=transport,
            max_concurrency=concurrency,
            timeout_s=timeout,
        )
    elif name == "openai":
        provider = OpenAILLM(
            settings.openai_api_key,
            chosen,
            transport=transport,
            max_concurrency=concurrency,
            timeout_s=timeout,
        )
    else:
        raise LLMError(f"{name!r} is not a live provider")
    cached = CachedLLM(provider, DiskCache(settings.llm_cache_dir))
    if not settings.llm_allow_mock_fallback:
        return cached
    return FallbackLLM(cached, MockLLM(default_mock_handlers()))
