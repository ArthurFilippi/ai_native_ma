"""Wire settings into a store and an LLM. Callers own the lifecycle (`await runtime.close()`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ainma.factbase import FactBase
from ainma.llm import LLM, build_llm
from ainma.llm.factory import build_judge_llm
from ainma.retrieval import RetrievalEngine
from ainma.settings import Settings, get_settings
from ainma.store import SqliteStore, Store

SYNTHETIC_ROOT = Path("data/synthetic")


@dataclass
class Runtime:
    """One per process. `engine` keeps the fitted retrieval indexes across requests (keyed by a
    fingerprint of the candidate set, so a new document refits); `judge_llm` is the judge model
    when one is configured apart from the writer."""

    settings: Settings
    store: Store
    llm: LLM
    judge_llm: LLM | None = None
    engine: RetrievalEngine = field(default_factory=RetrievalEngine)
    factbase: FactBase | None = None  # structured fact base of the loaded corpus (D92)

    async def close(self) -> None:
        await self.store.close()


async def open_runtime(settings: Settings | None = None) -> Runtime:
    settings = settings or get_settings()
    if settings.store_backend != "sqlite":
        raise NotImplementedError("the postgres store is a stretch milestone and not implemented")
    store = await SqliteStore.open(settings.sqlite_path)
    return Runtime(
        settings=settings,
        store=store,
        llm=build_llm(settings),
        judge_llm=build_judge_llm(settings),
        factbase=FactBase.load(SYNTHETIC_ROOT / str(settings.seed)),
    )
