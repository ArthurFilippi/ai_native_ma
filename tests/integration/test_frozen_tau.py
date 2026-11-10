"""The frozen abstention threshold is the one the pipeline ships with, and it can be recomputed."""

from __future__ import annotations

from pathlib import Path

from ainma.evaluation.run import calibrate_tau
from ainma.llm import build_mock_llm
from ainma.pipeline.config import DEFAULT_TAU, PipelineConfig
from ainma.synth.generate import generate


def test_the_pipeline_default_is_the_frozen_value() -> None:
    assert PipelineConfig().tau == DEFAULT_TAU
    assert 0.3 < DEFAULT_TAU < 0.9  # no longer the hand set 0.25 of the tiny fixture


async def test_calibrate_tau_prints_pooled_and_per_seed_values(tmp_path: Path) -> None:
    generate(1234, tmp_path)
    text = await calibrate_tau([1234], tmp_path, build_mock_llm())
    assert "seed 1234: tau " in text
    assert "pooled dev tau: " in text
    assert f"DEFAULT_TAU in pipeline/config.py: {DEFAULT_TAU}" in text
