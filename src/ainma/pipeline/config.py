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

    # the writer reads the most relevant passages of a wider list than `search` returns: trust
    # orders the evidence, it must not push a relevant press article out of reach
    retrieval: RetrievalConfig = Field(default_factory=lambda: RetrievalConfig(top_k=20))
    verifier: bool = True  # False: no checks at all, for the ablation
    drop_unverified: bool = True  # False: keep failing claims with Flag.UNVERIFIED
    tau: float = DEFAULT_TAU
    passage_min: float = 0.35  # relevance below which a passage never reaches the writer
    abstain_score: Literal["relevance", "final"] = "relevance"
    writer_passages: int = 8
    entity_gate: float = 0.5  # passages of documents that do not name the asked entity are dropped
    max_sub_questions: int = 4
    max_claims_per_sub_question: int = 4
    min_quote_chars: int = 10
    contradiction_tolerance: float = 0.005
    judge_concurrency: int = 8
    answers_log: Path | None = DEFAULT_ANSWERS_LOG  # None disables the log (tests)
