"""`make live-smoke` never runs without a live provider and its key, and reports the live path
with the writer and judge named."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainma.evaluation.live_smoke import NOT_EXECUTED, live_ready, render, run_smoke
from ainma.settings import Settings
from tests.unit.test_pipeline_judge_degraded import Recording

SEED_DIR = Path("data/synthetic/1234")


def test_no_key_means_not_executed() -> None:
    assert live_ready(Settings(_env_file=None)) == f"{NOT_EXECUTED}: LLM_PROVIDER is mock"
    reason = live_ready(Settings(llm_provider="gemini", gemini_api_key="", _env_file=None))
    assert reason is not None and reason.startswith(NOT_EXECUTED)
    fallback = Settings(
        llm_provider="gemini", gemini_api_key="k", llm_allow_mock_fallback=True, _env_file=None
    )
    assert "FALLBACK" in (live_ready(fallback) or "")
    assert live_ready(Settings(llm_provider="gemini", gemini_api_key="k", _env_file=None)) is None


@pytest.mark.skipif(not (SEED_DIR / "truth").is_dir(), reason="run `make data` first")
async def test_smoke_names_writer_and_judge() -> None:
    writer, judge = Recording("w", "writer-1"), Recording("j", "judge-1")
    result = await run_smoke(SEED_DIR, llm=writer, judge=judge, n=2, n_unanswerable=1)
    assert result["writer"] == "w writer-1" and result["judge"] == "j judge-1"
    assert len(result["rows"]) == 3
    text = render(result)
    assert "Writer: w writer-1. Judge: j judge-1." in text and "not the mock" in text
