"""Re-export of the truth schema (read only, owned by the orchestrator) for the generators."""

from __future__ import annotations

from ainma.truth import (
    BuyerTruth,
    ContradictionTruth,
    Fact,
    GenerationParams,
    JudgeLabel,
    KpiTruth,
    ManifestEntry,
    NewsFeedItem,
    Query,
    StaleCase,
    Unanswerable,
    UsersFile,
    split_of,
)

NewsItem = NewsFeedItem

__all__ = [
    "BuyerTruth",
    "ContradictionTruth",
    "Fact",
    "GenerationParams",
    "JudgeLabel",
    "KpiTruth",
    "ManifestEntry",
    "NewsFeedItem",
    "NewsItem",
    "Query",
    "StaleCase",
    "Unanswerable",
    "UsersFile",
    "split_of",
]
