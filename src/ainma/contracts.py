"""Executable interface contracts for ai_native_ma.

Reference copy. Phase A copies this file verbatim to src/ainma/contracts.py and
extends it only through DECISIONS.md entries. Every module exchanges these
objects, so the evaluation harness and the UI can be built against the example
payloads before the core pipeline exists.

Design rules encoded here:
- A claim is SOURCED (cites verbatim passages), INFERRED (derived from other
  claims, says so) or MISSING (nothing found). Never a smooth answer with no status.
- A citation points to an exact span (chunk, page, character offsets, quote).
- Source reliability is a tier derived from the document type (M&A analogue of
  an evidence level). Tier weights are priors to ablate, not ground truth.
- Contradictions are first class objects. The system never resolves them silently.
"""

from __future__ import annotations

from datetime import date
from enum import Enum, IntEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

VALUE_CONTRACT = (
    "I summarise the evidence clearly and show you the sources, "
    "so that you can examine them and make informed decisions."
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Documents, chunks, reliability tiers
# --------------------------------------------------------------------------


class DocType(str, Enum):
    SIGNED_AGREEMENT = "signed_agreement"  # executed SPA, merger agreement, signed NDA
    REGULATORY_FILING = "regulatory_filing"  # 8-K, proxy statement, fairness opinion, annual filing
    DEAL_DOCUMENT = "deal_document"  # CIM, management presentation, financial model
    COMPANY_REPORT = "company_report"  # annual report, investor presentation
    INTERNAL_REFERENCE = "internal_reference"  # bank playbooks, precedent memos (general layer)
    PRESS_RELEASE = "press_release"
    PRESS_ARTICLE = "press_article"
    WEB = "web"  # free web page


class SourceTier(IntEnum):
    T1 = 1
    T2 = 2
    T3 = 3
    T4 = 4
    T5 = 5


TIER_BY_DOCTYPE: dict[DocType, SourceTier] = {
    DocType.SIGNED_AGREEMENT: SourceTier.T1,
    DocType.REGULATORY_FILING: SourceTier.T1,
    DocType.DEAL_DOCUMENT: SourceTier.T2,
    DocType.COMPANY_REPORT: SourceTier.T2,
    DocType.INTERNAL_REFERENCE: SourceTier.T3,
    DocType.PRESS_RELEASE: SourceTier.T3,
    DocType.PRESS_ARTICLE: SourceTier.T4,
    DocType.WEB: SourceTier.T5,
}

# Priors used by the ranker. They are hyperparameters: the evaluation plan ablates them.
TIER_WEIGHT: dict[SourceTier, float] = {
    SourceTier.T1: 1.00,
    SourceTier.T2: 0.80,
    SourceTier.T3: 0.60,
    SourceTier.T4: 0.45,
    SourceTier.T5: 0.30,
}


class DocStatus(str, Enum):
    CURRENT = "current"
    SUPERSEDED = "superseded"  # replaced by a later version (draft vs executed, revised bid)
    WITHDRAWN = "withdrawn"  # retracted or corrected (M&A analogue of a retraction)


class DocumentMeta(Strict):
    id: str
    deal_id: str | None = None  # None means general knowledge layer
    entity_id: str | None = None  # e.g. buyer id the document is about
    title: str
    doc_type: DocType
    published_on: date | None = None
    status: DocStatus = DocStatus.CURRENT
    superseded_by: str | None = None
    n_pages: int = Field(ge=1)
    sha256: str
    synthetic: bool = True
    origin: str = "generator"  # generator | sec-edgar | simulated-connector | web | upload

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tier(self) -> SourceTier:
        return TIER_BY_DOCTYPE[self.doc_type]


class Chunk(Strict):
    id: str
    document_id: str
    deal_id: str | None = None
    entity_id: str | None = None
    page: int = Field(ge=1)
    char_start: int = Field(ge=0)  # offsets inside the page text
    char_end: int
    text: str
    kind: Literal["text", "table"] = "text"
    doc_type: DocType
    published_on: date | None = None

    @model_validator(mode="after")
    def _span_is_valid(self) -> Chunk:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self


# --------------------------------------------------------------------------
# Access control (applied before retrieval, never after)
# --------------------------------------------------------------------------


class Role(str, Enum):
    LEAD = "lead"
    MEMBER = "member"
    VIEWER = "viewer"


class User(Strict):
    id: str
    name: str


class Membership(Strict):
    deal_id: str
    user_id: str
    role: Role


class AccessContext(Strict):
    """Computed from memberships. The store filters on it inside the query."""

    user_id: str
    allowed_deal_ids: frozenset[str]
    include_general_layer: bool = True


class Deal(Strict):
    id: str
    name: str
    sector: str
    description: str = ""
    status: Literal["preparation", "marketing", "bids", "closed"] = "marketing"
    synthetic: bool = True
    # optional deal facts that prefill the stage 1 screening filters when none is typed (D87)
    geographies: list[str] = Field(default_factory=list)  # target region(s)
    ev_eur_m: float | None = None  # stated or indicative enterprise value
    buyer_types: list[BuyerType] = Field(default_factory=list)  # buyer types the seller accepts


# --------------------------------------------------------------------------
# Claims, citations, verification
# --------------------------------------------------------------------------


class Citation(Strict):
    chunk_id: str
    document_id: str
    doc_title: str
    doc_type: DocType
    tier: SourceTier
    published_on: date | None = None
    page: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int
    quote: str = Field(min_length=1)  # verbatim span, must be a substring of the chunk


class ClaimStatus(str, Enum):
    SOURCED = "sourced"  # fact quoted from sources
    INFERRED = "inferred"  # system deduction from other claims, shown as such
    MISSING = "missing"  # information not established by the sources


class Flag(str, Enum):
    STALE = "stale"  # source older than the freshness window
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"
    SINGLE_LOW_TIER_SOURCE = "single_low_tier_source"
    CONTRADICTED = "contradicted"
    UNVERIFIED = "unverified"  # verifier could not confirm support


class VerificationCheck(Strict):
    name: Literal["verbatim_span", "numeric_match", "binding", "judge"]
    passed: bool
    detail: str = ""


class Verification(Strict):
    supported: bool
    checks: list[VerificationCheck]
    judge_label: Literal["supported", "partial", "unsupported"] | None = None


class Claim(Strict):
    id: str
    text: str
    status: ClaimStatus
    citations: list[Citation] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)  # claim ids, for INFERRED
    verification: Verification | None = None
    flags: list[Flag] = Field(default_factory=list)
    # "structured": the value comes from the structured fact base and cites its provenance (D92)
    origin: Literal["text", "structured"] = "text"

    @model_validator(mode="after")
    def _status_is_consistent(self) -> Claim:
        if self.status is ClaimStatus.SOURCED and not self.citations:
            raise ValueError("a SOURCED claim needs at least one citation")
        if self.status is ClaimStatus.INFERRED and not self.derived_from:
            raise ValueError("an INFERRED claim must list the claims it derives from")
        if self.status is ClaimStatus.MISSING and self.citations:
            raise ValueError("a MISSING claim cannot carry citations")
        return self


class ContradictionSide(Strict):
    label: str  # e.g. "EUR 182.4m"
    claim_id: str
    citations: list[Citation]
    strength: float = Field(ge=0.0, le=1.0)  # tier weight x recency, explained in the UI


class Contradiction(Strict):
    id: str
    subject: str  # e.g. "Aurora FY2024 revenue"
    sides: list[ContradictionSide] = Field(min_length=2)
    stronger_side: int | None = None  # index, informative only
    note: str = "Sources disagree. The system does not pick a winner."


class MissingInfo(Strict):
    topic: str
    reason: Literal["not_found", "stale_only", "withdrawn_only"]


class RankedPassage(Strict):
    chunk_id: str
    rank: int = Field(ge=1)
    final_score: float
    components: dict[str, float]  # bm25, dense, rrf, rerank, tier_weight, recency, corroboration
    explanation: str  # one human readable line: why this passage ranks here


class Trace(Strict):
    provider: str
    model: str
    stage_latency_ms: dict[str, float] = Field(default_factory=dict)
    retrieved: list[RankedPassage] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    # the model that judged the claims; equal to provider/model when the writer judged (D88)
    judge_provider: str | None = None
    judge_model: str | None = None


class Answer(Strict):
    id: str
    deal_id: str | None
    user_id: str
    question: str
    sub_questions: list[str] = Field(default_factory=list)
    summary: str  # short, clear, first thing the user reads
    claims: list[Claim] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    missing: list[MissingInfo] = Field(default_factory=list)
    abstained: bool = False
    abstention_reason: str | None = None
    # a live call failed and the offline mock answered instead (opt in, D88): shown to the user
    degraded: bool = False
    degraded_reason: str | None = None
    trace: Trace
    value_contract: str = VALUE_CONTRACT

    @model_validator(mode="after")
    def _abstention_is_consistent(self) -> Answer:
        if self.abstained and any(c.status is not ClaimStatus.MISSING for c in self.claims):
            raise ValueError("an abstained answer cannot contain sourced or inferred claims")
        return self


# --------------------------------------------------------------------------
# Buy-side screening (two stages, explainable, user-weighted)
# --------------------------------------------------------------------------


class BuyerType(str, Enum):
    STRATEGIC = "strategic"
    FINANCIAL = "financial"


class BuyerProfile(Strict):
    id: str
    name: str
    buyer_type: BuyerType
    sectors: list[str]
    geographies: list[str]
    size_eur_m: float  # market cap (strategic) or AUM (financial)
    ticket_min_eur_m: float | None = None
    ticket_max_eur_m: float | None = None
    fund_vintage_year: int | None = None
    listed: bool = False
    synthetic: bool = True


class Criterion(Strict):
    key: str
    label: str
    kind: Literal["prefilter", "deep"]
    weight: float = Field(ge=0.0)
    dealbreaker: bool = False
    description: str = ""


class CriterionStatus(str, Enum):
    MET = "met"
    NOT_MET = "not_met"
    UNKNOWN = "unknown"  # no evidence found: shown as such, never guessed


class CriterionResult(Strict):
    criterion_key: str
    status: CriterionStatus
    rationale: str
    citations: list[Citation] = Field(default_factory=list)
    conflicting_evidence: bool = False


class BuyerCard(Strict):
    buyer: BuyerProfile
    stage1_passed: bool
    results: list[CriterionResult]
    score: float | None = None  # sum(w * met) / sum(w over known criteria), 0..1
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)  # share of total weight with evidence
    # range the score can still take once the unknown criteria are known (D86):
    # score_low counts every unknown as not met, score_high as met; the rank uses score_low
    score_low: float | None = None
    score_high: float | None = None
    contributions: dict[str, float] = Field(default_factory=dict)  # per criterion, sums to score
    dealbreakers: list[str] = Field(default_factory=list)
    rank: int | None = None


class ScreeningFilters(Strict):
    buyer_types: list[BuyerType] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    geographies: list[str] = Field(default_factory=list)
    min_size_eur_m: float | None = None
    max_size_eur_m: float | None = None


class ScreeningRequest(Strict):
    deal_id: str
    filters: ScreeningFilters = Field(default_factory=ScreeningFilters)
    weights: dict[str, float] = Field(default_factory=dict)  # criterion key -> weight override
    stage2_top_n: int = Field(default=10, ge=1, le=50)


class ScreeningResult(Strict):
    deal_id: str
    request: ScreeningRequest
    criteria: list[Criterion]
    cards: list[BuyerCard]


# --------------------------------------------------------------------------
# KPI extraction
# --------------------------------------------------------------------------


class KpiDef(Strict):
    id: str
    name: str
    category: str
    unit: str
    kind: Literal["extract", "compute"]
    formula: str | None = None  # e.g. "(gross_profit / revenue) * 100"
    depends_on: list[str] = Field(default_factory=list)
    time_periods: list[str] = Field(default_factory=lambda: ["annual"])


class KpiValue(Strict):
    kpi_id: str
    period: str  # e.g. "FY2024"
    value: float | None
    unit: str
    status: Literal["sourced", "computed", "missing"]
    citations: list[Citation] = Field(default_factory=list)
    formula_inputs: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _status_is_consistent(self) -> KpiValue:
        if self.status == "sourced" and not self.citations:
            raise ValueError("a sourced KPI value needs a citation")
        if self.status == "computed" and not self.formula_inputs:
            raise ValueError("a computed KPI value must expose its inputs")
        if self.status == "missing" and self.value is not None:
            raise ValueError("a missing KPI value has no value")
        return self


# --------------------------------------------------------------------------
# Market intelligence connectors (simulated implementations first)
# --------------------------------------------------------------------------


class ConnectorItem(Strict):
    connector: str  # "simulated-news", later "crunchbase", "pitchbook", ...
    retrieved_on: date
    title: str
    url: str | None = None
    published_on: date | None = None
    doc_type: DocType = DocType.PRESS_ARTICLE
    text: str
    simulated: bool = True
