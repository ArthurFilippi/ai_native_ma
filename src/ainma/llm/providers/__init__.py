"""Provider implementations. `build_live_llm` is what `ainma.llm.factory` wires for live keys."""

from __future__ import annotations

import httpx

from ainma.llm.base import LLM, LLMError
from ainma.settings import Settings


def build_live_llm(settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> LLM:
    """`FallbackLLM(CachedLLM(provider, DiskCache(settings.llm_cache_dir)), mock)`.

    The mock answers when the live provider fails and says so in `Usage.fallback_from`. `model`
    comes from `settings.llm_model` (empty means the provider default). `transport` lets tests
    inject recorded responses.
    """
    from ainma.llm.cache import CachedLLM, DiskCache, FallbackLLM
    from ainma.llm.mock import MockLLM
    from ainma.llm.providers.gemini import GeminiLLM
    from ainma.llm.providers.mock_tasks import default_mock_handlers
    from ainma.llm.providers.openai import OpenAILLM

    provider: LLM
    if settings.llm_provider == "gemini":
        provider = GeminiLLM(settings.gemini_api_key, settings.llm_model, transport=transport)
    elif settings.llm_provider == "openai":
        provider = OpenAILLM(settings.openai_api_key, settings.llm_model, transport=transport)
    else:
        raise LLMError(f"{settings.llm_provider!r} is not a live provider")
    cached = CachedLLM(provider, DiskCache(settings.llm_cache_dir))
    return FallbackLLM(cached, MockLLM(default_mock_handlers()))
