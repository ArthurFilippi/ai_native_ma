"""Pipeline configuration. One object, so ablations are a diff between two configs."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ainma.retrieval.config import RetrievalConfig

DEFAULT_TAU = 0.595212
"""Abstention threshold on the retrieval relevance of the best passage (0 to 1), frozen. It is the
pooled DEV threshold of the five seeds, chosen so that at most 10 percent of the dev answerable
queries fall below it. Recompute it with `python -m ainma.evaluation.run --calibrate-tau --seeds 5`
(it prints the pooled value and the per seed values) and copy the pooled value here whenever the
retrieval or the reranker changes; the evaluation report prints this value next to the recomputed
one so that drift is visible. The API, the CLI, the demo and the test split all use it. See
docs/DECISIONS.md D24 and D82."""

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
    # a sub-question asking for one keyed value is answered from the structured fact base when
    # one is passed to `ask` (D92); False: text search only, for the ablation
    structured_routing: bool = True
    answers_log: Path | None = DEFAULT_ANSWERS_LOG  # None disables the log (tests)
