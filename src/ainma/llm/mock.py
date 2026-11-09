"""Deterministic offline provider. Each task is a pure routine registered by name."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

from pydantic import BaseModel

from ainma.llm.base import LLMError, T, Usage

MockHandler = Callable[[str, str, type[BaseModel]], BaseModel]
"""(system, user, schema) -> instance of schema. Pure and deterministic."""

MOCK_PROVIDER = "mock"
MOCK_MODEL = "mock-extractive-v1"


class MockLLM:
    provider = MOCK_PROVIDER
    model = MOCK_MODEL

    def __init__(self, handlers: Mapping[str, MockHandler]) -> None:
        self._handlers = dict(handlers)

    async def complete_json(
        self, *, task: str, system: str, user: str, schema: type[T], stage: str
    ) -> tuple[T, Usage]:
        handler = self._handlers.get(task)
        if handler is None:
            raise LLMError(f"mock task {task!r} is not implemented")
        started = time.perf_counter()
        result = handler(system, user, schema)
        if not isinstance(result, schema):
            raise LLMError(f"mock task {task!r} returned {type(result).__name__}, not {schema}")
        usage = Usage(
            provider=self.provider,
            model=self.model,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
        return result, usage
