"""Wire settings into a store and an LLM. Callers own the lifecycle (`await runtime.close()`)."""

from __future__ import annotations

from dataclasses import dataclass

from ainma.llm import LLM, build_llm
from ainma.settings import Settings, get_settings
from ainma.store import SqliteStore, Store


@dataclass
class Runtime:
    settings: Settings
    store: Store
    llm: LLM

    async def close(self) -> None:
        await self.store.close()


async def open_runtime(settings: Settings | None = None) -> Runtime:
    settings = settings or get_settings()
    if settings.store_backend != "sqlite":
        raise NotImplementedError("the postgres store is a stretch milestone and not implemented")
    store = await SqliteStore.open(settings.sqlite_path)
    return Runtime(settings=settings, store=store, llm=build_llm(settings))
