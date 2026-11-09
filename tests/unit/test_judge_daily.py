from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainma.contracts import Answer, ClaimStatus
from ainma.judge import RegressionCase, append_case, judge_answer
from ainma.judge.daily import confirm, run_daily, select_answers
from ainma.llm import build_mock_llm
from ainma.pipeline import PipelineConfig, ask
from ainma.pipeline.log import entry_for
from ainma.store import SqliteStore


async def _answers(store: SqliteStore) -> list[Answer]:
    access = await store.access_for("u_analyst")
    llm = build_mock_llm()
    config = PipelineConfig(answers_log=None)
    return [
        await ask(q, store=store, access=access, deal_id="deal_aurora", llm=llm, config=config)
        for q in ("What was FY2024 revenue?", "What is the CEO's compensation package?")
    ]


async def test_honest_answers_score_full_faithfulness(tiny_store: SqliteStore) -> None:
    honest, abstention = await _answers(tiny_store)
    judged = await judge_answer(honest, build_mock_llm())
    assert judged.faithfulness == 1.0 and judged.relevance == 1.0 and not judged.flagged
    assert set(judged.claim_labels.values()) == {"supported"}
    assert judged.self_judged  # the mock writes and judges: reported, not hidden
    skipped = await judge_answer(abstention, build_mock_llm())
    assert skipped.faithfulness is None and skipped.relevance is None and not skipped.flagged


async def test_a_doctored_claim_is_flagged(tiny_store: SqliteStore) -> None:
    honest, _ = await _answers(tiny_store)
    first = honest.claims[0]
    assert first.status is ClaimStatus.SOURCED
    doctored = honest.model_copy(
        update={
            "claims": [
                first.model_copy(
                    update={"text": "Net revenue for FY2024 reached EUR 190.0 million."}
                ),
                *honest.claims[1:],
            ]
        }
    )
    judged = await judge_answer(doctored, build_mock_llm())
    assert judged.flagged and judged.flags[0] == "unsupported_claim:c1"
    assert judged.faithfulness is not None and judged.faithfulness < 1.0


async def test_low_relevance_is_flagged(tiny_store: SqliteStore) -> None:
    honest, _ = await _answers(tiny_store)
    off_topic = honest.model_copy(update={"question": "Who signed the NDA with the bidder panel?"})
    judged = await judge_answer(off_topic, build_mock_llm())
    assert "low_relevance" in judged.flags


async def test_daily_replays_the_log_and_prints_flagged_items(
    tiny_store: SqliteStore, tmp_path: Path
) -> None:
    honest, abstention = await _answers(tiny_store)
    doctored = honest.model_copy(
        update={
            "id": "ans_doctored",
            "claims": [
                honest.claims[0].model_copy(
                    update={"text": "Revenue was EUR 190.0 million in FY2024."}
                )
            ],
        }
    )
    log = tmp_path / "answers.jsonl"
    with log.open("w") as handle:
        for answer, stamp in (
            (honest, "2026-11-09"),
            (abstention, "2026-11-09"),
            (doctored, "2026-11-10"),
        ):
            entry = entry_for(answer, dropped=[], config_hash="x")
            entry["logged_at"] = f"{stamp}T10:00:00+00:00"
            handle.write(json.dumps(entry) + "\n")
    assert len(select_answers(log, None)) == 3 and len(select_answers(log, "2026-11-10")) == 1
    report = await run_daily(log, None, build_mock_llm())
    assert "FLAG ans_doctored" in report and "unsupported_claim:c1" in report
    assert f"FLAG {honest.id}" not in report
    assert "3 answers judged, 1 flagged." in report
    assert "SAME model writes and judges" in report
    assert (await run_daily(tmp_path / "missing.jsonl", None, build_mock_llm())).startswith(
        "0 answers"
    )


async def test_regression_helper_appends_json_lines_once(tmp_path: Path) -> None:
    case = RegressionCase(
        id="ans_1",
        question="q",
        deal_id="deal_aurora",
        user_id="u_analyst",
        flags=["unsupported_claim:c1"],
    )
    path = await append_case(case, directory=tmp_path / "eval" / "regression")
    await append_case(case, directory=tmp_path / "eval" / "regression")
    await append_case(
        case.model_copy(update={"id": "ans_2"}), directory=tmp_path / "eval" / "regression"
    )
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    assert [x["id"] for x in lines] == ["ans_1", "ans_2"]
    assert RegressionCase.model_validate(lines[0]) == case


async def test_confirm_appends_a_logged_answer(tiny_store: SqliteStore, tmp_path: Path) -> None:
    honest, _ = await _answers(tiny_store)
    log = tmp_path / "answers.jsonl"
    log.write_text(json.dumps(entry_for(honest, dropped=[], config_hash="x")) + "\n")
    path = await confirm(log, honest.id[:8], "checked by hand", build_mock_llm(), tmp_path / "reg")
    assert path is not None
    saved = json.loads(path.read_text().splitlines()[0])
    assert saved["id"] == honest.id and saved["note"] == "checked by hand"
    assert await confirm(log, "ans_nope", "", build_mock_llm(), tmp_path / "reg") is None


def test_main_prints_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from ainma.judge.daily import main

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    assert main(["--log", str(tmp_path / "none.jsonl")]) == 0
    assert capsys.readouterr().out == "0 answers judged, 0 flagged.\n"
    assert main(["--log", str(tmp_path / "none.jsonl"), "confirm", "ans_x"]) == 1
