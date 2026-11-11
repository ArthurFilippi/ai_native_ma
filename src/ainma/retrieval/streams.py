"""Source streams and query intent for the multi-stream ranker (D100).

Every passage belongs to one stream: the deal's data room, the firm's internal knowledge, the
buyers' own documents, or news (simulated feed or live web). A question has an intent: a `fact`
about the deal (a metric, a period), `market` (news, recent deals, rumours), or `neutral`. The
source ranker multiplies a passage's score by the weight of its stream for the question's intent,
so news cannot crowd the data room out of a financial question, and a market question reaches the
news first. The weights are priors set by principle, not tuned on the evaluation; see the
stream ablation in `eval/results/STREAMS.md`.
"""

from __future__ import annotations

import re
from typing import Literal

from ainma.contracts import DocType, DocumentMeta
from ainma.retrieval.lexicon import detect_periods, target_metrics

Stream = Literal["dataroom", "knowledge", "buyers", "news"]
Intent = Literal["fact", "market", "neutral"]

NEWS_TYPES = {DocType.PRESS_ARTICLE, DocType.PRESS_RELEASE, DocType.WEB}
NEWS_ORIGINS = {"simulated-connector", "web"}

DEFAULT_STREAM_WEIGHTS: dict[Intent, dict[Stream, float]] = {
    "fact": {"dataroom": 1.0, "knowledge": 0.9, "buyers": 0.9, "news": 0.8},
    "market": {"dataroom": 0.85, "knowledge": 0.85, "buyers": 1.0, "news": 1.0},
    "neutral": {"dataroom": 1.0, "knowledge": 1.0, "buyers": 1.0, "news": 1.0},
}

_MARKET = re.compile(
    r"\b(news|recent(?:ly)?|latest|announce[sd]?|rumou?r(?:s|ed)?|reported(?:ly)?|"
    r"acquir(?:e|ed|es|ing|ition|itions)|bought|buys|bid|offer|deal activity|"
    r"appoint(?:s|ed)?|chief executive|ceo change|press)\b",
    re.IGNORECASE,
)


def stream_of(document: DocumentMeta) -> Stream:
    if document.origin in NEWS_ORIGINS:
        return "news"
    if document.deal_id is not None:
        # press items planted in a data room are still news for the analyst
        return "news" if document.doc_type in NEWS_TYPES else "dataroom"
    if document.entity_id is not None:
        return "buyers"
    return "news" if document.doc_type in NEWS_TYPES else "knowledge"


def query_intent(query: str) -> Intent:
    """`fact` when the question names a metric (with or without a period) and no market word;
    `market` when it uses a market word; `neutral` otherwise."""
    market = _MARKET.search(query) is not None
    if target_metrics(query) and not market:
        return "fact"
    if market:
        return "market"
    return "fact" if detect_periods(query) else "neutral"
