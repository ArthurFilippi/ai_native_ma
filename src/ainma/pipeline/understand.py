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
from ainma.pipeline.rules import subject_of
from ainma.pipeline.schemas import UnderstandRequest, UnderstandResult
from ainma.retrieval.entities import entity_phrases, entity_tokens
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
_INTERROGATIVE = r"(?:how|what|whether|which|who|when|where|why)"
# a second question inside the sentence: always a new sub-question, with or without a metric
_STRONG = re.compile(
    rf"\s*(?:;|,\s*(?:and|as well as|then)\b|\band\b(?=\s+{_INTERROGATIVE}\b))\s*", re.IGNORECASE
)
# a plain conjunction or comma: a new sub-question only when both sides ask for a metric
_WEAK = re.compile(r"\s*(?:,|\band\b|\bas well as\b)\s*", re.IGNORECASE)
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


def _cut(body: str, pattern: re.Pattern[str], protected: list[tuple[int, int]]) -> list[str]:
    pieces: list[str] = []
    cursor = 0
    for match in pattern.finditer(body):
        if any(a < match.start() < b for a, b in protected):
            continue
        pieces.append(body[cursor : match.start()])
        cursor = match.end()
    pieces.append(body[cursor:])
    return [p.strip() for p in pieces if p.strip()]


def _clauses(body: str) -> list[str]:
    """Split a compound question into the questions it asks.

    Strong joints (`; `, `, and`, `and how / what / whether / which / who ...`) always start a new
    sub-question, so `gross margin and what is the CEO's compensation` is two questions even
    though the second names no metric. Plain commas and `and` split only where both sides ask for
    a metric: `revenue change between FY2023 and FY2024` stays one question, and a metric name
    (`earnings before interest, tax, depreciation and amortisation`) is never cut.
    """
    protected = [(a, b) for _, a, b in find_metrics(body)]
    clauses: list[str] = []
    for strong in _cut(body, _STRONG, protected):
        if clauses and _GROWTH.search(strong) and not detect_metrics(strong):
            # `... and how did it grow`: the same metric over time, answered by the prior
            # period sub-question that `understand_rules` adds, not a topic of its own
            clauses[-1] = f"{clauses[-1]} and {strong}"
            continue
        weak: list[str] = []
        for piece in _cut(strong, _WEAK, [(a, b) for _, a, b in find_metrics(strong)]):
            if weak and (not detect_metrics(piece) or not detect_metrics(weak[-1])):
                weak[-1] = f"{weak[-1]} {piece}"
            else:
                weak.append(piece)
        clauses.extend(weak)
    return clauses


def understand_rules(question: str) -> UnderstandResult:
    text = question.strip()
    metrics, periods = target_metrics(text), detect_periods(text)
    entities = _entities(text)
    body = text.rstrip("?.! ")
    clauses = _clauses(body)
    subject = subject_of(text)
    sub_questions: list[str] = []
    if len(clauses) >= 2:
        for clause in clauses:
            extra_periods = [p for p in periods if p not in detect_periods(clause)]
            named = set(entity_tokens(clause))
            wanted = set(entity_tokens(subject))
            names = [f"({subject})"] if subject and not wanted <= named else []
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
