"""Executable schema of the generated corpus and its ground truth.

The `data` agent writes these files, the `eval`, `core` and `biz` agents read them. Layout of one
seed (`data/synthetic/<seed>/`):

    manifest.json              list[ManifestEntry], every document file with its metadata
    <kb|deal_aurora|buyers|news>/...   document files (pdf, docx, xlsx, txt)
    news/items.json            list[NewsFeedItem], served by the simulated connector
    truth/news_events.json     list[NewsEventTruth]       (events of the feed, duplicates grouped)
    truth/deals.json           list[Deal]
    truth/users.json           UsersFile
    truth/buyers.json          list[BuyerProfile]
    truth/facts.json           list[Fact]
    truth/queries.json         list[Query]                (answerable, graded relevance)
    truth/unanswerable.json    list[Unanswerable]
    truth/contradictions.json  list[ContradictionTruth]   (pairs, controls, superseded, withdrawn)
    truth/stale.json           list[StaleCase]
    truth/kpi_truth.json       list[KpiTruth]
    truth/buyer_truth.json     list[BuyerTruth]
    truth/judge_labels.json    list[JudgeLabel]           (adversarial claims, constructed labels)
    truth/params.json          GenerationParams           (difficulty knobs actually used)
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Literal

from pydantic import Field

from ainma.contracts import (
    ConnectorItem,
    CriterionStatus,
    DocStatus,
    DocType,
    Membership,
    Strict,
    User,
)

Split = Literal["dev", "test"]


def split_of(query_id: str, dev_share: float = 0.3) -> Split:
    """Deterministic 30/70 split by hash of the query id (never by position or content)."""
    digest = hashlib.sha256(query_id.encode("utf-8")).digest()
    return "dev" if digest[0] / 255.0 < dev_share else "test"


class GenerationParams(Strict):
    seed: int
    paraphrase_rate: float = Field(ge=0.0, le=1.0)
    hard_negative_rate: float = Field(ge=0.0, le=1.0)
    generator_version: str


class ManifestEntry(Strict):
    """Document file plus the metadata the loader cannot derive. `n_pages` and `sha256` are
    computed by the parser when the document is loaded."""

    id: str
    path: str  # relative to the seed directory
    format: Literal["pdf", "docx", "xlsx", "txt"]
    deal_id: str | None = None
    entity_id: str | None = None
    title: str
    doc_type: DocType
    published_on: date | None = None
    status: DocStatus = DocStatus.CURRENT
    superseded_by: str | None = None
    synthetic: bool = True
    origin: str = "generator"


class UsersFile(Strict):
    users: list[User]
    memberships: list[Membership]


class NewsFeedItem(ConnectorItem):
    entity: str  # entity id or deal id the item is about


class NewsEventTruth(Strict):
    """One market event of the news feed and every item that reports it (D93).

    `status`: `confirmed`, `unconfirmed` (a rumour nobody confirmed or denied), `denied` (a rumour
    denied later: never a fact), `corrected` (a figure replaced by a later correction; `value`
    is the corrected figure)."""

    id: str
    kind: Literal["acquisition", "leadership_change", "rumour", "price"]
    entity: str  # buyer id
    counterparty: str  # target company, appointed person
    event_date: date
    status: Literal["confirmed", "unconfirmed", "denied", "corrected"]
    value: float | None = None  # EUR m, for `price`
    item_titles: list[str] = Field(min_length=1)


class Fact(Strict):
    """A planted fact. The primary span is where the generator wrote it, `support_chunk_ids`
    lists every stored chunk that contains it (paraphrases and tables included), re-derived by
    `python -m ainma.synth verify`."""

    id: str
    deal_id: str | None
    entity: str
    metric: str  # e.g. "revenue", "gross_margin", "top_customer_share"
    period: str  # e.g. "FY2024"
    value: float
    unit: str  # e.g. "EUR m", "%"
    document_id: str
    page: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int
    quote: str
    support_chunk_ids: list[str]
    keywords: list[str] = Field(default_factory=list)  # metric and period words for matching


class Query(Strict):
    id: str
    deal_id: str | None
    text: str
    kind: Literal["single_fact", "multi_fact", "comparison", "hard_negative", "paraphrased"]
    gold_fact_ids: list[str] = Field(min_length=1)
    relevance: dict[str, int]  # chunk id -> 2 (contains the fact) | 1 (supporting context)
    paraphrased: bool = False


class Unanswerable(Strict):
    id: str
    deal_id: str | None
    text: str
    reason: str
    hard: bool = False  # shares vocabulary with the corpus


class ContradictionTruth(Strict):
    id: str
    kind: Literal["contradiction", "consistent_control", "superseded", "withdrawn"]
    deal_id: str | None
    subject: str  # e.g. "Aurora FY2024 revenue"
    entity: str
    metric: str
    period: str
    fact_ids: list[str] = Field(min_length=2)  # one fact per document
    document_ids: list[str] = Field(min_length=2)
    stronger_document_id: str | None = None  # higher tier or more recent, informative only
    expected: Literal["contradiction", "no_contradiction", "flag_superseded", "flag_withdrawn"]
    query_id: str | None = None  # question that should surface it


class StaleCase(Strict):
    id: str
    query_id: str
    fact_id: str
    reason: str = "every supporting source is older than the freshness window"


class KpiTruth(Strict):
    deal_id: str
    kpi_id: str
    period: str
    value: float
    unit: str
    kind: Literal["extract", "compute"]


class BuyerTruth(Strict):
    deal_id: str
    buyer_id: str
    criterion_key: str
    status: CriterionStatus


class JudgeLabel(Strict):
    id: str
    claim: str
    chunk_id: str
    label: Literal["supported", "partial", "unsupported"]
    perturbation: Literal[
        "none", "altered_number", "altered_period", "altered_entity", "half_true", "unrelated"
    ]
    split: Split
    quote: str | None = None  # verbatim span offered with the claim, when relevant
