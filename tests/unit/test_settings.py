from __future__ import annotations

import pytest

from ainma.settings import DEFAULT_SEED, Settings


def test_defaults_are_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("LLM_PROVIDER", "STORE_BACKEND", "SEED"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.llm_provider == "mock"
    assert settings.store_backend == "sqlite"
    assert settings.seed == DEFAULT_SEED
    assert settings.gemini_api_key == ""
