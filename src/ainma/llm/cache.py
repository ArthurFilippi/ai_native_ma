"""Disk cache and fallback wrappers around any `LLM`."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from ainma.llm.base import LLM, LLMError, T, Usage

logger = logging.getLogger(__name__)


def cache_key(*, provider: str, model: str, task: str, system: str, user: str, schema: str) -> str:
    payload = json.dumps([provider, model, task, system, user, schema], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DiskCache:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def _path(self, key: str) -> Path:
        return self._dir / key[:2] / f"{key}.json"

    def _read(self, key: str) -> dict[str, object] | None:
        path = self._path(key)
        if not path.exists():
            return None
        data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def _write(self, key: str, value: dict[str, object]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    async def get(self, key: str) -> dict[str, object] | None:
        return await asyncio.to_thread(self._read, key)

    async def put(self, key: str, value: dict[str, object]) -> None:
        await asyncio.to_thread(self._write, key, value)


class CachedLLM:
    """Reruns are free and reproducible: the key is (provider, model, task, prompts, schema)."""

    def __init__(self, inner: LLM, cache: DiskCache) -> None:
        self._inner = inner
        self._cache = cache
        self.provider = inner.provider
        self.model = inner.model

    async def complete_json(
        self, *, task: str, system: str, user: str, schema: type[T], stage: str
    ) -> tuple[T, Usage]:
        key = cache_key(
            provider=self.provider,
            model=self.model,
            task=task,
            system=system,
            user=user,
            schema=schema.__name__,
        )
        hit = await self._cache.get(key)
        if hit is not None:
            parsed = schema.model_validate(hit["value"])
            usage = Usage.model_validate(hit["usage"]).model_copy(update={"cached": True})
            return parsed, usage
        parsed, usage = await self._inner.complete_json(
            task=task, system=system, user=user, schema=schema, stage=stage
        )
        await self._cache.put(
            key, {"value": parsed.model_dump(mode="json"), "usage": usage.model_dump()}
        )
        return parsed, usage


class FallbackLLM:
    """Use `primary`; when it fails, answer with `fallback` and say so in `Usage.fallback_from`."""

    def __init__(self, primary: LLM, fallback: LLM) -> None:
        self._primary = primary
        self._fallback = fallback
        self.provider = primary.provider
        self.model = primary.model

    async def complete_json(
        self, *, task: str, system: str, user: str, schema: type[T], stage: str
    ) -> tuple[T, Usage]:
        try:
            return await self._primary.complete_json(
                task=task, system=system, user=user, schema=schema, stage=stage
            )
        except LLMError as error:
            logger.warning("provider %s failed (%s), falling back to mock", self.provider, error)
            parsed, usage = await self._fallback.complete_json(
                task=task, system=system, user=user, schema=schema, stage=stage
            )
            return parsed, usage.model_copy(update={"fallback_from": self.provider})
