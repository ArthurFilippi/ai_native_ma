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
    )


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
    return await market_events(deal_id, store=runtime.store, access=access, llm=runtime.llm)


async def refine(
    runtime: Runtime, access: AccessContext, text: str, current: ScreeningRequest
) -> RefineOutcome:
    regions = sorted({g for b in await runtime.store.list_buyers() for g in b.geographies})
    return await refine_request(text, current, geographies=regions, llm=runtime.llm)
