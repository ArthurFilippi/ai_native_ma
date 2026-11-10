"""Build the configured LLM. Live providers are wrapped with a disk cache and a visible fallback."""

from __future__ import annotations

from ainma.llm.base import LLM
from ainma.llm.mock import MockLLM
from ainma.llm.providers import build_live_llm
from ainma.llm.providers.mock_tasks import default_mock_handlers
from ainma.settings import Settings


def build_mock_llm() -> LLM:
    return MockLLM(default_mock_handlers())


def build_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "mock":
        return build_mock_llm()
    return build_live_llm(settings)


def build_judge_llm(settings: Settings) -> LLM | None:
    """The judge model when `JUDGE_PROVIDER` or `JUDGE_MODEL` is set, else None (the writer
    judges its own claims, and the trace says so)."""
    if not settings.judge_provider and not settings.judge_model:
        return None
    provider = settings.judge_provider or settings.llm_provider
    if provider == "mock":
        return build_mock_llm()
    return build_live_llm(settings, provider_name=provider, model=settings.judge_model)
