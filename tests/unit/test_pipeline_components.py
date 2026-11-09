"""Understand, mock tasks, abstention calibration, summary, CLI and import hygiene."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ainma.contracts import Answer
from ainma.llm import LLMError, build_mock_llm
from ainma.llm.providers.mock_tasks import default_mock_handlers, judge_relevance, judge_support
from ainma.llm.tasks import ALL_TASKS, TASK_KPI_PARSE
from ainma.pipeline.abstain import calibrate_tau
from ainma.pipeline.cli import main
from ainma.pipeline.schemas import UnderstandResult
from ainma.pipeline.understand import topic_of, understand_rules

ROOT = Path(__file__).resolve().parents[2]
CIM_SENTENCE = "Net revenue for FY2024 reached EUR 182.4 million (FY2023: EUR 168.0 million)."


def test_understand_splits_and_adds_the_prior_period_for_growth() -> None:
    result = understand_rules("What was Aurora's FY2024 revenue and how did it grow?")
    assert result.sub_questions == [
        "What was Aurora's FY2024 revenue and how did it grow?",  # "how did it grow" is no topic
        "FY2023 revenue Aurora",
    ]
    assert result.metrics == ["revenue"] and result.periods == ["FY2024"]
    assert result.entities == ["Aurora"]


def test_understand_keeps_single_questions_whole_and_shares_the_period() -> None:
    assert understand_rules("What is the CEO's compensation package?").sub_questions == [
        "What is the CEO's compensation package?"
    ]
    multi = understand_rules("What are the gross margin and the largest customer in FY2024?")
    assert multi.sub_questions == [
        "What are the gross margin FY2024",
        "the largest customer in FY2024",
    ]
    assert len(understand_rules("a, b, c, d, e, f, g, h").sub_questions) <= 4


def test_topic_of_strips_question_words() -> None:
    assert topic_of("What is the CEO's compensation package?") == "CEO's compensation package"
    assert topic_of("What was FY2024 revenue?") == "FY2024 revenue"
    assert topic_of("revenue") == "revenue"


def test_mock_judge_labels_by_number_binding_entity_and_words() -> None:
    quote = CIM_SENTENCE
    assert judge_support("FY2024 revenue reached EUR 182.4 million.", [quote]).label == "supported"
    assert (
        judge_support("Revenue reached EUR 190.0 million in FY2024.", [quote]).label
        == "unsupported"
    )
    # numbers present in the quote but bound to another period
    assert (
        judge_support("FY2023 revenue reached EUR 182.4 million.", [quote]).label == "unsupported"
    )
    assert (
        judge_support(
            "FY2024 revenue was EUR 182.4 million and EBITDA EUR 40 million.", [quote]
        ).label
        == "partial"
    )
    assert (
        judge_support("Borealis revenue for FY2024 reached EUR 182.4 million.", [quote]).label
        == "unsupported"
    )
    assert (
        judge_support("The weather was sunny in Paris yesterday afternoon.", [quote]).label
        == "unsupported"
    )
    assert judge_support("Net revenue was strong for the year.", [quote]).label in {
        "supported",
        "partial",
    }


def test_mock_relevance_is_term_coverage() -> None:
    assert judge_relevance("What was FY2024 revenue?", CIM_SENTENCE).score == 1.0
    assert judge_relevance("What was FY2024 revenue?", "Bidder communication.").score == 0.0


async def test_mock_registers_every_task_except_kpi_parse() -> None:
    handlers = default_mock_handlers()
    assert set(handlers) == set(ALL_TASKS) - {TASK_KPI_PARSE}
    with pytest.raises(LLMError, match="not implemented"):
        await build_mock_llm().complete_json(
            task=TASK_KPI_PARSE, system="", user="{}", schema=UnderstandResult, stage="t"
        )


def test_calibrate_tau_by_hand() -> None:
    answerable = [0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0]
    unanswerable = [0.0, 0.1, 0.3, 0.45, 0.6]
    result = calibrate_tau(answerable, unanswerable, max_false_abstention=0.10)
    assert result.tau == 0.4  # only 0.2 (1 of 10 answerable) falls below
    assert result.false_abstention == pytest.approx(0.1)
    assert result.correct_abstention == pytest.approx(3 / 5)  # 0.0, 0.1 and 0.3 are below 0.4
    strict = calibrate_tau(answerable, unanswerable, max_false_abstention=0.0)
    assert strict.tau == 0.2 and strict.false_abstention == 0.0
    with pytest.raises(ValueError):
        calibrate_tau([], unanswerable)


def test_importing_in_either_order_has_no_cycle() -> None:
    for first in ("ainma.pipeline", "ainma.llm", "ainma.llm.providers.mock_tasks"):
        code = f"import {first}; import ainma.pipeline, ainma.llm, ainma.retrieval"
        done = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env={"PYTHONPATH": str(ROOT / "src")},
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr


def test_cli_prints_a_valid_answer_and_the_outsider_finds_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        [
            "ask",
            "--tiny",
            "--no-log",
            "--user",
            "u_analyst",
            "--deal",
            "deal_aurora",
            "What was FY2024 revenue?",
        ]
    )
    assert code == 0
    answer = Answer.model_validate(json.loads(capsys.readouterr().out))
    assert not answer.abstained
    assert answer.claims[0].citations[0].quote
    code = main(
        [
            "ask",
            "--tiny",
            "--no-log",
            "--user",
            "u_outsider",
            "--deal",
            "deal_aurora",
            "What was FY2024 revenue?",
        ]
    )
    outsider = Answer.model_validate(json.loads(capsys.readouterr().out))
    assert code == 0 and outsider.abstained and outsider.trace.retrieved == []
    assert main(["ask", "--tiny", "--no-log", "--user", "nobody", "x"]) == 2
