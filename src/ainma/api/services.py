"""The one place where the API reaches the pipeline, screening, KPI and connector modules."""

from __future__ import annotations

from pathlib import Path

from ainma.connectors.run import run_live_search, run_market_intel
from ainma.connectors.tavily import TavilyNewsConnector
from ainma.contracts import (
    AccessContext,
    Answer,
    DocumentMeta,
    KpiValue,
    MarketEvent,
    ScreeningRequest,
    ScreeningResult,
)
from ainma.kpi import extract_kpis
from ainma.news import market_events
from ainma.news.events import NEWS_TYPES
from ainma.pipeline import ask as pipeline_ask
from ainma.runtime import Runtime
from ainma.screening import run_screening
from ainma.screening.refine import RefineOutcome, refine_request

SYNTHETIC_ROOT = Path("data/synthetic")


def seed_dir(runtime: Runtime) -> Path:
    return SYNTHETIC_ROOT / str(runtime.settings.seed)


async def ask(runtime: Runtime, access: AccessContext, deal_id: str, question: str) -> Answer:
    return await pipeline_ask(
        question,
        store=runtime.store,
        access=access,
        deal_id=deal_id,
        llm=runtime.llm,
        judge_llm=runtime.judge_llm,
        engine=runtime.engine,
        factbase=runtime.factbase,
        events=await deal_events(runtime, access, deal_id),
    )


async def deal_events(runtime: Runtime, access: AccessContext, deal_id: str) -> list[MarketEvent]:
    """The deal's consolidated news events, recomputed only when its news documents change."""
    news = tuple(
        sorted(
            d.id
            for d in await runtime.store.list_documents(access, deal_id)
            if d.deal_id == deal_id and d.doc_type in NEWS_TYPES
        )
    )
    if not news:
        return []
    cached = runtime.events_cache.get(deal_id)
    if cached is None or cached[0] != news:
        found = await market_events(deal_id, store=runtime.store, access=access, llm=runtime.llm)
        runtime.events_cache[deal_id] = (news, found)
    return runtime.events_cache[deal_id][1]


async def screening(
    runtime: Runtime, access: AccessContext, request: ScreeningRequest
) -> ScreeningResult:
    return await run_screening(
        request, store=runtime.store, access=access, llm=runtime.llm, factbase=runtime.factbase
    )


async def kpis(runtime: Runtime, access: AccessContext, deal_id: str) -> list[KpiValue]:
    return await extract_kpis(deal_id, store=runtime.store, access=access, llm=runtime.llm)


async def market_intel(runtime: Runtime, access: AccessContext, deal_id: str) -> int:
    return await run_market_intel(
        deal_id, store=runtime.store, access=access, seed_dir=seed_dir(runtime)
    )


async def live_search(
    runtime: Runtime, access: AccessContext, deal_id: str, query: str
) -> list[DocumentMeta]:
    connector = TavilyNewsConnector(runtime.settings.tavily_api_key)
    return await run_live_search(
        deal_id, query, store=runtime.store, access=access, connector=connector
    )


async def events(runtime: Runtime, access: AccessContext, deal_id: str) -> list[MarketEvent]:
    return await deal_events(runtime, access, deal_id)


async def refine(
    runtime: Runtime, access: AccessContext, text: str, current: ScreeningRequest
) -> RefineOutcome:
    regions = sorted({g for b in await runtime.store.list_buyers() for g in b.geographies})
    return await refine_request(text, current, geographies=regions, llm=runtime.llm)
