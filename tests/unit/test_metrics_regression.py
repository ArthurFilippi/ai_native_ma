"""Regression loader and replay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainma.evaluation.adapter import Adapter
from ainma.evaluation.regression import RegressionCase, load_cases, replay
from ainma.evaluation.smoke import load_smoke_store
from ainma.llm import build_mock_llm


def case(case_id: str, **expected: object) -> dict[str, object]:
    return {
        "id": case_id,
        "question": "What was Aurora net revenue for FY2024?",
        "deal_id": "deal_aurora",
        "user_id": "u_analyst",
        "expected": {"abstain": False, "must_contain": [], "must_not_contain": [], **expected},
        "note": "confirmed by hand",
    }


def write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_empty_or_missing_directory_is_zero_cases(tmp_path: Path) -> None:
    assert load_cases(tmp_path) == []
    assert load_cases(tmp_path / "absent") == []
    (tmp_path / ".gitkeep").write_text("")
    assert load_cases(tmp_path) == []


def test_cases_load_in_name_order_and_blank_lines_are_skipped(tmp_path: Path) -> None:
    write(tmp_path / "b.jsonl", [case("c2")])
    (tmp_path / "a.jsonl").write_text(json.dumps(case("c1")) + "\n\n", encoding="utf-8")
    assert [c.id for c in load_cases(tmp_path)] == ["c1", "c2"]


def test_invalid_line_names_file_and_line(tmp_path: Path) -> None:
    (tmp_path / "a.jsonl").write_text(json.dumps(case("ok")) + "\n{bad json\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"a\.jsonl:2"):
        load_cases(tmp_path)


async def test_replay_counts_passes_and_names_failures() -> None:
    store = await load_smoke_store()
    adapter = Adapter(store=store, llm=build_mock_llm(), use_real=False)
    cases = [
        RegressionCase.model_validate(case("passes", must_contain=["182.4"])),
        RegressionCase.model_validate(case("missing_text", must_contain=["no such text"])),
        RegressionCase.model_validate(case("forbidden", must_not_contain=["182.4"])),
        RegressionCase.model_validate(case("wrong_abstention", abstain=True)),
        RegressionCase.model_validate({**case("ghost"), "user_id": "u_nobody"}),
    ]
    outcome = await replay(cases, adapter=adapter, store=store)
    assert (outcome.n_cases, outcome.n_passed) == (5, 1)
    reasons = {f["id"]: f["reason"] for f in outcome.failures}
    assert set(reasons) == {"missing_text", "forbidden", "wrong_abstention", "ghost"}
    assert "unknown user" in reasons["ghost"]
    assert "abstained=False" in reasons["wrong_abstention"]
    await store.close()
