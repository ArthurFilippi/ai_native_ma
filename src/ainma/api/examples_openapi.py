"""Example payloads attached to the OpenAPI schema (copies of the specification examples)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EXAMPLES = Path(__file__).parent / "examples"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    return data


ANSWER_EXAMPLES: dict[str, dict[str, Any]] = {
    "contradiction": _load("answer_contradiction.json"),
    "abstention": _load("answer_abstention.json"),
}
SCREENING_EXAMPLES: dict[str, dict[str, Any]] = {"screening": _load("screening_result.json")}
