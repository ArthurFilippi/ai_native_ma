"""Replay the answer log through the judge and print what looks wrong.

    python -m ainma.judge.daily [--log data/cache/answers.jsonl] [--date 2026-11-10]
    python -m ainma.judge.daily confirm ANSWER_ID --note "why"

`make judge-daily` calls the first form. `confirm` appends a flagged answer to
`eval/regression/` after a human has checked it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from ainma.contracts import Answer
from ainma.judge.regression import RegressionCase, append_case
from ainma.judge.scoring import JudgedAnswer, judge_answer
from ainma.llm import LLM, build_llm
from ainma.pipeline.config import DEFAULT_ANSWERS_LOG
from ainma.pipeline.log import read_entries
from ainma.settings import get_settings


def select_answers(log: Path, day: str | None) -> list[Answer]:
    """Answers of the log, optionally those logged on `day` (UTC, `YYYY-MM-DD`). When an id was
    logged several times the newest entry wins."""
    latest: dict[str, Answer] = {}
    for entry in read_entries(log):
        if day is None or str(entry.get("logged_at", "")).startswith(day):
            answer = Answer.model_validate(entry["answer"])
            latest[answer.id] = answer
    return list(latest.values())


def render(judged: Sequence[JudgedAnswer]) -> str:
    lines: list[str] = []
    flagged = [j for j in judged if j.flagged]
    if judged:
        writer, judge = judged[0].writer_model, judged[0].judge_model
        note = "SAME model writes and judges (self preference risk)" if writer == judge else ""
        lines.append(f"judge model: {judge}; writer model: {writer}. {note}".strip())
    for item in flagged:
        faith = "n/a" if item.faithfulness is None else f"{item.faithfulness:.2f}"
        rel = "n/a" if item.relevance is None else f"{item.relevance:.2f}"
        lines.append(
            f"FLAG {item.answer_id} faithfulness={faith} relevance={rel} "
            f"flags={','.join(item.flags)} question={item.question!r}"
        )
    lines.append(f"{len(judged)} answers judged, {len(flagged)} flagged.")
    return "\n".join(lines) + "\n"


async def run_daily(log: Path, day: str | None, llm: LLM) -> str:
    answers = select_answers(log, day)
    return render([await judge_answer(a, llm) for a in answers])


async def confirm(log: Path, answer_id: str, note: str, llm: LLM, directory: Path) -> Path | None:
    matches = [a for a in select_answers(log, None) if a.id.startswith(answer_id)]
    if not matches:
        return None
    answer = matches[-1]
    judged = await judge_answer(answer, llm)
    case = RegressionCase(
        id=answer.id,
        question=answer.question,
        deal_id=answer.deal_id,
        user_id=answer.user_id,
        flags=judged.flags,
        note=note,
    )
    return await append_case(case, directory=directory)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ainma.judge.daily")
    parser.add_argument("--log", type=Path, default=DEFAULT_ANSWERS_LOG)
    parser.add_argument("--date", default=None, help="only answers logged on this UTC day")
    commands = parser.add_subparsers(dest="command")
    confirm_cmd = commands.add_parser("confirm", help="append a checked flag to eval/regression/")
    confirm_cmd.add_argument("answer_id")
    confirm_cmd.add_argument("--note", default="")
    confirm_cmd.add_argument("--directory", type=Path, default=Path("eval/regression"))
    args = parser.parse_args(argv)
    llm = build_llm(get_settings())
    if args.command == "confirm":
        path = asyncio.run(confirm(args.log, args.answer_id, args.note, llm, args.directory))
        if path is None:
            sys.stderr.write(f"no answer {args.answer_id!r} in {args.log}\n")
            return 1
        sys.stdout.write(f"appended to {path}\n")
        return 0
    sys.stdout.write(asyncio.run(run_daily(args.log, args.date, llm)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
