"""Append-only answer log (JSON lines) behind `make inspect` and `make judge-daily`."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from ainma.contracts import Answer
from ainma.pipeline.schemas import DroppedClaim


def entry_for(
    answer: Answer, *, dropped: list[DroppedClaim], config_hash: str, now: datetime | None = None
) -> dict[str, object]:
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    return {
        "id": answer.id,
        "logged_at": stamp,
        "question": answer.question,
        "config_hash": config_hash,
        "dropped": [d.model_dump(mode="json") for d in dropped],
        "answer": answer.model_dump(mode="json"),
    }


def _append(path: Path, entry: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


async def append_answer(path: Path, entry: dict[str, object]) -> None:
    await asyncio.to_thread(_append, path, entry)


def read_entries(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    entries: list[dict[str, object]] = []
    for line in lines:
        if line.strip():
            entry = json.loads(line)
            if isinstance(entry, dict):
                entries.append(entry)
    return entries
