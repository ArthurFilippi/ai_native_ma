"""Input and output schemas of every LLM task of the pipeline.

Requests are strict and travel as JSON in the user prompt, so the deterministic mock parses
exactly what a live model reads. Results ignore unknown keys: a live model may add some.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ainma.contracts import Strict


class Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---- understand ---------------------------------------------------------------------------------


class UnderstandRequest(Strict):
    question: str


class UnderstandResult(Lenient):
    sub_questions: list[str]
    entities: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    periods: list[str] = Field(default_factory=list)


# ---- write --------------------------------------------------------------------------------------


class NumberedPassage(Strict):
    n: int = Field(ge=1)
    chunk_id: str
    text: str
    doc_title: str
    tier: int
    published_on: date | None = None


class WriteRequest(Strict):
    question: str
    sub_questions: list[str]
    passages: list[NumberedPassage]
    max_claims: int = Field(default=4, ge=1)  # per sub-question


class DraftEvidence(Lenient):
    passage: int
    quote: str


class DraftClaim(Lenient):
    id: str
    text: str
    status: Literal["sourced", "inferred"]
    evidence: list[DraftEvidence] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)


class WriteResult(Lenient):
    claims: list[DraftClaim]
    missing: list[str] = Field(default_factory=list)


# ---- judge --------------------------------------------------------------------------------------


class JudgeRequest(Strict):
    claim: str
    quotes: list[str]
    context: str = ""


class JudgeResult(Lenient):
    label: Literal["supported", "partial", "unsupported"]
    rationale: str = ""


class RelevanceRequest(Strict):
    question: str
    answer: str


class RelevanceResult(Lenient):
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


# ---- extract facts ------------------------------------------------------------------------------


class ExtractFactsRequest(Strict):
    text: str


class FactItem(Lenient):
    metric: str
    period: str | None = None
    value: float
    unit: str
    label: str


class ExtractFactsResult(Lenient):
    facts: list[FactItem]


# ---- bookkeeping --------------------------------------------------------------------------------


class DroppedClaim(Strict):
    """A claim that did not reach the answer, kept in the log so the verifier can be measured."""

    text: str
    stage: Literal["writer", "verifier"]
    reason: str
