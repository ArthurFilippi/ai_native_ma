"""Pipeline configuration. One object, so ablations are a diff between two configs."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ainma.retrieval.config import RetrievalConfig

DEFAULT_TAU = 0.25
"""Provisional abstention threshold on the relevance score (0 to 1). Hand set on the tiny
fixture corpus only; to be recalibrated on the DEV split of the generated corpus with
`ainma.pipeline.abstain.calibrate_tau`. See docs/DECISIONS.md D24."""

DEFAULT_ANSWERS_LOG = Path("data/cache/answers.jsonl")


class PipelineConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    verifier: bool = True  # False: no checks at all, for the ablation
    drop_unverified: bool = True  # False: keep failing claims with Flag.UNVERIFIED
    tau: float = DEFAULT_TAU
    abstain_score: Literal["relevance", "final"] = "relevance"
    writer_passages: int = 8
    max_sub_questions: int = 4
    max_claims_per_sub_question: int = 4
    min_quote_chars: int = 10
    contradiction_tolerance: float = 0.005
    judge_concurrency: int = 8
    answers_log: Path | None = DEFAULT_ANSWERS_LOG  # None disables the log (tests)
