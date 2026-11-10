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
from ainma.retrieval.lexicon import (
    METRIC_BY_KEY,
    detect_metrics,
    detect_periods,
    previous_period,
)
from ainma.retrieval.text import tokenize

_GROWTH = re.compile(
    r"\b(grow|grew|grown|growth|increase[ds]?|decline[ds]?|decrease[ds]?|change[ds]?|"
    r"evolution|trend|year[- ]on[- ]year|yoy)\b",
    re.IGNORECASE,
)
_SPLIT = re.compile(r"\s*(?:;|,|\band\b|\bas well as\b)\s*", re.IGNORECASE)
_LEADING = re.compile(
    r"^(?:what|who|which|when|where|why|how|is|are|was|were|does|did|do|has|have|can|could|"
    r"tell me|give me|list|show me|show|compare)\b(?:\s+(?:is|are|was|were|the|a|an|of|about))*\s*",
    re.IGNORECASE,
)
_QUESTION_WORDS = frozenset(
    [
        "What",
        "Who",
        "Which",
        "When",
        "Where",
        "Why",
        "How",
        "Is",
        "Are",
        "Was",
        "Were",
        "Does",
        "Did",
        "Do",
        "Has",
        "Have",
        "Can",
        "Could",
        "Tell",
        "Give",
        "List",
        "Show",
        "Compare",
    ]
)
_ENTITY = re.compile(r"\b[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*)*")
MAX_SUB_QUESTIONS = 4


def topic_of(text: str) -> str:
    """`What is the CEO's compensation package?` becomes `CEO's compensation package`."""
    topic = _LEADING.sub("", text.strip().rstrip("?.! ")).strip()
    return topic or text.strip().rstrip("?")


def _entities(question: str) -> list[str]:
    found: dict[str, None] = {}
    for match in _ENTITY.finditer(question):
        words = [
            w
            for w in match.group(0).split()
            if w not in _QUESTION_WORDS and not re.fullmatch(r"(?:FY|H[12]|Q[1-4])\d*", w)
        ]
        if words:
            found.setdefault(" ".join(words))
    return list(found)


def understand_rules(question: str) -> UnderstandResult:
    text = question.strip()
    metrics, periods = detect_metrics(text), detect_periods(text)
    entities = _entities(text)
    body = text.rstrip("?.! ")
    clauses = [c for c in _SPLIT.split(body) if c]
    useful = [c for c in clauses if len(tokenize(c)) >= 2 or detect_metrics(c)]
    sub_questions: list[str] = []
    if len(useful) >= 2:
        for clause in useful:
            extra = [p for p in periods if p not in detect_periods(clause)]
            sub_questions.append(" ".join([clause, *extra]).strip())
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
