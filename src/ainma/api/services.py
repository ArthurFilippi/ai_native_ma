"""The one place where the API reaches the core, screening, KPI and connector modules.

Those modules are delivered by other agents. Each entry point is resolved at call time with
`importlib`. When the target is missing the example payloads of `examples/` answer instead, and
the caller reports `stub` in the `X-Ainma-Backend` header so nobody mistakes them for real output.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import TypeAdapter

from ainma.contracts import AccessContext, Answer, KpiValue, ScreeningRequest, ScreeningResult
from ainma.runtime import Runtime

log = logging.getLogger(__name__)

EXAMPLES = Path(__file__).parent / "examples"
Backend = Literal["real", "stub"]
T = TypeVar("T")


@dataclass(frozen=True)
class Served[T]:
    value: T
    backend: Backend


def _resolve(module_name: str, attribute: str) -> Callable[..., Awaitable[Any]] | None:
    """The entry point, or None when its module (or the function) is not there yet."""
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if module_name == missing or module_name.startswith(missing + "."):
            return None
        raise  # the target exists but one of its own imports is broken: surface it
    target = getattr(module, attribute, None)
    if inspect.ismodule(target):  # `ainma.pipeline.ask` may be a submodule that defines `ask`
        target = getattr(target, attribute, None)
    return target if callable(target) else None


def _example[M](adapter_type: type[M], name: str) -> M:
    return TypeAdapter(adapter_type).validate_json((EXAMPLES / name).read_text(encoding="utf-8"))


async def ask(
    runtime: Runtime, access: AccessContext, deal_id: str, question: str
) -> Served[Answer]:
    real = _resolve("ainma.pipeline", "ask")
    if real is not None:
        answer: Answer = await real(
            question, store=runtime.store, access=access, deal_id=deal_id, llm=runtime.llm
        )
        return Served(answer, "real")
    log.info("ainma.pipeline.ask is not available, serving the example answer")
    name = (
        "answer_contradiction.json" if "revenue" in question.lower() else "answer_abstention.json"
    )
    stub = _example(Answer, name).model_copy(
        update={"user_id": access.user_id, "deal_id": deal_id, "question": question}
    )
    return Served(stub, "stub")


async def screening(
    runtime: Runtime, access: AccessContext, request: ScreeningRequest
) -> Served[ScreeningResult]:
    real = _resolve("ainma.screening", "run_screening")
    if real is not None:
        result: ScreeningResult = await real(
            request, store=runtime.store, access=access, llm=runtime.llm
        )
        return Served(result, "real")
    log.info("ainma.screening.run_screening is not available, serving the example result")
    stub = _example(ScreeningResult, "screening_result.json").model_copy(
        update={"deal_id": request.deal_id, "request": request}
    )
    return Served(stub, "stub")


async def kpis(runtime: Runtime, access: AccessContext, deal_id: str) -> Served[list[KpiValue]]:
    real = _resolve("ainma.kpi", "extract_kpis")
    if real is not None:
        values: list[KpiValue] = await real(
            deal_id, store=runtime.store, access=access, llm=runtime.llm
        )
        return Served(values, "real")
    log.info("ainma.kpi.extract_kpis is not available, serving the example values")
    return Served(_example(list[KpiValue], "kpis.json"), "stub")


async def market_intel(runtime: Runtime, access: AccessContext, deal_id: str) -> Served[int]:
    real = _resolve("ainma.connectors.run", "run_market_intel")
    if real is not None:
        seed_dir = Path("data/synthetic") / str(runtime.settings.seed)
        ingested: int = await real(deal_id, store=runtime.store, access=access, seed_dir=seed_dir)
        return Served(ingested, "real")
    log.info("ainma.connectors.run.run_market_intel is not available, nothing was ingested")
    return Served(0, "stub")
