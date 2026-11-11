"""The out of distribution set is well formed and its runner scores it (D96)."""

from __future__ import annotations

import json
from pathlib import Path

from ainma.evaluation.ood import DATASET, SYSTEMS, render, run_ood
from ainma.llm import build_mock_llm


def test_every_gold_string_is_in_a_document() -> None:
    texts = [p.read_text("utf-8") for p in (DATASET / "docs").glob("*.txt")]
    questions = json.loads((DATASET / "questions.json").read_text("utf-8"))
    assert 30 <= len(questions) <= 50
    for q in questions:
        assert all(any(g in t for t in texts) for g in q["gold"]), q["id"]
    assert all("SYNTHETIC DOCUMENT" in t for t in texts)


async def test_runner_scores_every_question(tmp_path: Path) -> None:
    result = await run_ood(DATASET, build_mock_llm())
    s = result["summary"]
    assert s["n_answerable"] + s["n_unanswerable"] == len(result["rows"])
    assert set(s["recall_at_10"]) == set(SYSTEMS)
    assert "Out of distribution check" in render(result)
