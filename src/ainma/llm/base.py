"""LLM interface, usage accounting and shared JSON validation with one retry."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when a provider fails or returns output that never validates."""


class Usage(BaseModel):
    """Per call accounting. `fallback_from` is set when a live provider failed and the mock
    answered instead, so the substitution is never silent."""

    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: float = 0.0
    cached: bool = False
    fallback_from: str | None = None

    def merged(self, other: Usage) -> Usage:
        cost = None
        if self.cost_usd is not None or other.cost_usd is not None:
            cost = (self.cost_usd or 0.0) + (other.cost_usd or 0.0)
        return self.model_copy(
            update={
                "input_tokens": self.input_tokens + other.input_tokens,
                "output_tokens": self.output_tokens + other.output_tokens,
                "cost_usd": cost,
                "latency_ms": self.latency_ms + other.latency_ms,
            }
        )


class LLM(Protocol):
    provider: str
    model: str

    async def complete_json(
        self, *, task: str, system: str, user: str, schema: type[T], stage: str
    ) -> tuple[T, Usage]: ...


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def strip_json_fences(raw: str) -> str:
    match = _FENCE.match(raw.strip())
    return match.group(1) if match else raw.strip()


class RawJsonLLM(ABC):
    """Base for live providers: implement `_raw`, get schema validation and one retry."""

    provider: str
    model: str

    @abstractmethod
    async def _raw(
        self, *, system: str, user: str, json_schema: dict[str, Any], stage: str
    ) -> tuple[str, Usage]:
        """Return the raw model text and its usage."""

    async def complete_json(
        self, *, task: str, system: str, user: str, schema: type[T], stage: str
    ) -> tuple[T, Usage]:
        json_schema = schema.model_json_schema()
        raw, usage = await self._raw(system=system, user=user, json_schema=json_schema, stage=stage)
        try:
            return schema.model_validate_json(strip_json_fences(raw)), usage
        except (ValidationError, json.JSONDecodeError) as first_error:
            retry_user = (
                f"{user}\n\nYour previous reply failed validation: {first_error}\n"
                "Reply again with valid JSON only."
            )
            raw2, usage2 = await self._raw(
                system=system, user=retry_user, json_schema=json_schema, stage=stage
            )
            try:
                parsed = schema.model_validate_json(strip_json_fences(raw2))
            except (ValidationError, json.JSONDecodeError) as second_error:
                raise LLMError(
                    f"task {task!r}: output failed validation twice: {second_error}"
                ) from second_error
            return parsed, usage.merged(usage2)
