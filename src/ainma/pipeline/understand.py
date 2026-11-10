"""Understand: sub-questions, entities, metrics and periods.

`understand_rules` is the rule based routine behind the mock provider; a live model gets the same
request and returns the same schema. `topic_of` turns a question into the short topic shown in
`MissingInfo`.
"""

from __future__ import annotations

import re

from ainma.llm.base import LLM, Usage
from ainma.llm.tasks import TASK_UNDERSTAND
from ainma.pipeline import prompts
from ainma.pipeline.schemas import UnderstandRequest, UnderstandResult
from ainma.retrieval.entities import entity_phrases
from ainma.retrieval.lexicon import (
    METRIC_BY_KEY,
    detect_metrics,
    detect_periods,
    find_metrics,
    previous_period,
    target_metrics,
)

_GROWTH = re.compile(
    r"\b(grow|grew|grown|growth|increase[ds]?|decline[ds]?|decrease[ds]?|change[ds]?|"
    r"evolution|trend|year[- ]on[- ]year|yoy)\b",
    re.IGNORECASE,
)
_SPLIT = re.compile(r"\s*(?:;|,|\band\b|\bas well as\b)\s*", re.IGNORECASE)
_LEADING = re.compile(
    r"^(?:how\s+(?:many|much|long|large|high)|what|who|which|when|where|why|how|is|are|was|were|"
    r"does|did|do|has|have|can|could|tell me|give me|list|show me|show|compare)\b"
    r"(?:\s+(?:is|are|was|were|did|does|do|the|a|an|of|about)\b)*\s*",
    re.IGNORECASE,
)
MAX_SUB_QUESTIONS = 4


def topic_of(text: str) -> str:
    """`What is the CEO's compensation package?` becomes `CEO's compensation package`."""
    topic = _LEADING.sub("", text.strip().rstrip("?.! ")).strip()
    return topic or text.strip().rstrip("?")


def _entities(question: str) -> list[str]:
    return entity_phrases(question)


def _pieces(body: str) -> list[str]:
    """`body` cut at `and`, commas and semicolons that are not inside a metric name (`earnings
    before interest, tax, depreciation and amortisation`)."""
    protected = [(a, b) for _, a, b in find_metrics(body)]
    pieces: list[str] = []
    cursor = 0
    for match in _SPLIT.finditer(body):
        if any(a < match.start() < b for a, b in protected):
            continue
        pieces.append(body[cursor : match.start()])
        cursor = match.end()
    pieces.append(body[cursor:])
    return [p.strip() for p in pieces if p.strip()]


def _clauses(body: str) -> list[str]:
    """Compound questions are split where both sides ask for a metric: `revenue change between
    FY2023 and FY2024` stays one question."""
    clauses: list[str] = []
    for piece in _pieces(body):
        if clauses and (not detect_metrics(piece) or not detect_metrics(clauses[-1])):
            clauses[-1] = f"{clauses[-1]} {piece}"
        else:
            clauses.append(piece)
    return clauses


def understand_rules(question: str) -> UnderstandResult:
    text = question.strip()
    metrics, periods = target_metrics(text), detect_periods(text)
    entities = _entities(text)
    body = text.rstrip("?.! ")
    clauses = _clauses(body)
    sub_questions: list[str] = []
    if len(clauses) >= 2:
        for clause in clauses:
            extra_periods = [p for p in periods if p not in detect_periods(clause)]
            names = [] if entity_phrases(clause) else entities
            sub_questions.append(" ".join([clause, *extra_periods, *names]).strip())
    else:
        sub_questions.append(text)
    if _GROWTH.search(text) and len(metrics) >= 1 and len(periods) == 1:
        prior = previous_period(periods[0])
        if prior:
            label = METRIC_BY_KEY[metrics[0]].label
            subject = " ".join(entities)
            sub_questions.append(f"{prior} {label} {subject}".strip())
    return UnderstandResult(
        sub_questions=sub_questions[:MAX_SUB_QUESTIONS],
        entities=entities,
        metrics=metrics,
        periods=periods,
    )


async def understand(llm: LLM, question: str) -> tuple[UnderstandResult, Usage]:
    request = UnderstandRequest(question=question)
    return await llm.complete_json(
        task=TASK_UNDERSTAND,
        system=prompts.UNDERSTAND,
        user=request.model_dump_json(),
        schema=UnderstandResult,
        stage="understand",
    )
