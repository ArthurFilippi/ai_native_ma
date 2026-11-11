"""LLM assisted stage 2 (D95): the model may turn an `unknown` criterion into a verdict, only with
evidence that code verifies.

The deterministic rules run first and stay the baseline. For a criterion they leave `unknown`,
the model reads numbered evidence: the buyer's structured facts (each with its provenance) and
the retrieved passages of the buyer's documents. It returns a verdict, a rationale and, per piece
of evidence it relies on, the item number and a verbatim quote. Code keeps a citation only when
the quote is a span of that item; a `met` or `not_met` without one verified citation stays
`unknown`. The model never sees or writes a query, and the documented parameters are passed as
parameters, never as sources.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ainma.contracts import Chunk, Citation, CriterionResult, CriterionStatus, Strict
from ainma.factbase import BuyerFilterRequest, FactBase
from ainma.llm.base import LLM
from ainma.llm.tasks import TASK_ASSESS_CRITERION
from ainma.screening.deep import DeepContext

logger = logging.getLogger(__name__)

MAX_PASSAGES = 6
TOPICS: dict[str, str] = {
    "ticket_fit": "fund size equity ticket investment range",
    "ev_ratio": "market capitalisation enterprise value size",
    "fund_lifecycle": "investment period fund vintage",
    "recent_activity": "acquisition acquired completed",
    "integration_bandwidth": "acquisition integration acquired",
    "antitrust": "market share position",
    "regulatory_fdi": "state ownership sovereign defence regulatory",
}
BUYER_METRICS = (
    "aum",
    "market_cap",
    "ticket_min",
    "ticket_max",
    "fund_vintage_year",
    "investment_period_end_year",
    "portfolio_companies",
    "market_share",
)


class Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class EvidenceItem(Strict):
    n: int
    source: str  # document title, tier and date, or "structured fact base"
    text: str


class AssessRequest(Strict):
    criterion: str
    label: str
    description: str
    buyer: str
    deal: str  # the deal facts the rules use (sector, indicative size), parameters marked
    parameters: dict[str, str]
    evidence: list[EvidenceItem]


class AssessEvidence(Lenient):
    n: int
    quote: str


class AssessResult(Lenient):
    status: Literal["met", "not_met", "unknown"]
    rationale: str = ""
    evidence: list[AssessEvidence] = Field(default_factory=list)


ASSESS_PROMPT = """You assess one screening criterion for one buyer of a sell-side M&A process.
Use only the numbered evidence. Return `met` or `not_met` only when an item states what decides
the criterion; otherwise `unknown`. For every item you rely on, give its number and a verbatim
quote from its text. Parameters are assumptions of the banker, not facts: say so when you use one.
Never guess a missing figure. Return JSON only."""


async def _items(
    ctx: DeepContext, key: str, factbase: FactBase | None
) -> tuple[list[EvidenceItem], dict[int, Citation | Chunk]]:
    items: list[EvidenceItem] = []
    sources: dict[int, Citation | Chunk] = {}
    if factbase is not None:
        access = ctx.finder.access
        for metric in BUYER_METRICS:
            for fact in factbase.buyer_facts(
                BuyerFilterRequest(metric=metric, buyer_ids=[ctx.buyer.id]), access=access
            ):
                n = len(items) + 1
                p = fact.provenance
                items.append(
                    EvidenceItem(
                        n=n,
                        source=f"structured fact base, from {p.doc_title} (tier {int(p.tier)}, "
                        f"{p.published_on})",
                        text=p.quote,
                    )
                )
                sources[n] = p.citation()
    for chunk in (await ctx.finder.buyer_chunks(ctx.buyer, TOPICS.get(key, key)))[:MAX_PASSAGES]:
        n = len(items) + 1
        source = f"{chunk.doc_type.value}, {chunk.published_on}"
        items.append(EvidenceItem(n=n, source=source, text=chunk.text))
        sources[n] = chunk
    return items, sources


def _deal_text(ctx: DeepContext) -> str:
    parts = [f"target sectors: {', '.join(ctx.target_sectors)}", f"reference date: {ctx.as_of}"]
    if ctx.economics is not None:
        parts.append(f"indicative size: {ctx.economics.ev_basis}; {ctx.economics.cheque_basis}")
    return "; ".join(parts)


async def assess_unknown(
    baseline: CriterionResult,
    ctx: DeepContext,
    *,
    label: str,
    description: str,
    llm: LLM,
    factbase: FactBase | None,
) -> CriterionResult:
    """The baseline when it has a verdict; otherwise the model's verdict if verified, else the
    baseline `unknown` with a note."""
    if baseline.status is not CriterionStatus.UNKNOWN:
        return baseline
    key = baseline.criterion_key
    items, sources = await _items(ctx, key, factbase)
    if not items:
        return baseline
    request = AssessRequest(
        criterion=key,
        label=label,
        description=description,
        buyer=ctx.buyer.name,
        deal=_deal_text(ctx),
        parameters={k: str(v) for k, v in asdict(ctx.params).items()},
        evidence=items,
    )
    result, _ = await llm.complete_json(
        task=TASK_ASSESS_CRITERION,
        system=ASSESS_PROMPT,
        user=request.model_dump_json(),
        schema=AssessResult,
        stage="screening",
    )
    if result.status == "unknown":
        return baseline
    citations: list[Citation] = []
    for cited in result.evidence:
        source = sources.get(cited.n)
        quote = cited.quote.strip()
        if source is None or not quote:
            continue
        if isinstance(source, Citation):
            if quote in source.quote and source not in citations:
                citations.append(source)
            continue
        if quote in source.text:
            citation = await ctx.finder.cite_quote(source, quote)
            if citation not in citations:
                citations.append(citation)
    if not citations:
        logger.info("%s %s: model verdict without verified evidence", ctx.buyer.id, key)
        return baseline.model_copy(
            update={
                "rationale": f"{baseline.rationale} A model proposed `{result.status}` without "
                "verified evidence; not used."
            }
        )
    return CriterionResult(
        criterion_key=key,
        status=CriterionStatus(result.status),
        rationale=f"Model assessment ({llm.provider} {llm.model}), evidence verified by code: "
        f"{result.rationale}".strip(),
        citations=citations,
    )


def mock_assess(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    """The offline mock does not assess criteria: it always answers `unknown`, so the rules
    alone decide in mock runs and the assisted mode is measured only with a live model."""
    return AssessResult(status="unknown", rationale="offline mock: no assessment")
