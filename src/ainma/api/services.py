"""The one place where the API reaches the pipeline, screening, KPI and connector modules."""

from __future__ import annotations

from pathlib import Path

from ainma.connectors.run import run_market_intel
from ainma.contracts import AccessContext, Answer, KpiValue, ScreeningRequest, ScreeningResult
from ainma.kpi import extract_kpis
from ainma.pipeline import ask as pipeline_ask
from ainma.runtime import Runtime
from ainma.screening import run_screening

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
    return await run_screening(request, store=runtime.store, access=access, llm=runtime.llm)


async def kpis(runtime: Runtime, access: AccessContext, deal_id: str) -> list[KpiValue]:
    return await extract_kpis(deal_id, store=runtime.store, access=access, llm=runtime.llm)


async def market_intel(runtime: Runtime, access: AccessContext, deal_id: str) -> int:
    return await run_market_intel(
        deal_id, store=runtime.store, access=access, seed_dir=seed_dir(runtime)
    )
