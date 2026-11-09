"""Confirmed judge flags become permanent regression cases.

`append_case` writes one JSON line per case under `eval/regression/` (the `eval` agent reads and
replays them on every `make eval`). Appending a case whose id is already present is a no-op.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pydantic import BaseModel

DEFAULT_DIRECTORY = Path("eval/regression")
CASES_FILE = "cases.jsonl"


class RegressionCase(BaseModel):
    id: str  # the answer id, stable across reruns of the same question and configuration
    question: str
    deal_id: str | None
    user_id: str
    flags: list[str]
    note: str = ""
    expected: str = "every sourced claim is supported by its own quote"


def _append(case: RegressionCase, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / CASES_FILE
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("id") == case.id:
                return path
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(case.model_dump(mode="json"), ensure_ascii=False) + "\n")
    return path


async def append_case(case: RegressionCase, *, directory: Path = DEFAULT_DIRECTORY) -> Path:
    return await asyncio.to_thread(_append, case, directory)
