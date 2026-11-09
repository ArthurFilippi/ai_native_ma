"""Build the configured LLM. Live providers are wrapped with a disk cache and a visible fallback."""

from __future__ import annotations

from ainma.llm.base import LLM, LLMError
from ainma.llm.mock import MockLLM
from ainma.llm.providers.mock_tasks import default_mock_handlers
from ainma.settings import Settings


def build_mock_llm() -> LLM:
    return MockLLM(default_mock_handlers())


def build_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "mock":
        return build_mock_llm()
    raise LLMError(f"provider {settings.llm_provider!r} is not wired yet (delivered with core)")
