"""Replay of confirmed failures. Each case is a JSON line appended by the judge monitoring
(`ainma.judge.regression.append_case`) and becomes a permanent test run by every evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import Field, ValidationError

from ainma.contracts import Answer, Strict
from ainma.evaluation.adapter import Adapter
from ainma.store import Store, UnknownUserError


class RegressionExpected(Strict):
    abstain: bool
    must_contain: list[str] = Field(default_factory=list)
    must_not_contain: list[str] = Field(default_factory=list)


class RegressionCase(Strict):
    id: str
    question: str
    deal_id: str | None
    user_id: str
    expected: RegressionExpected
    note: str = ""


@dataclass
class RegressionOutcome:
    n_cases: int = 0
    n_passed: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)


def load_cases(directory: Path) -> list[RegressionCase]:
    """Every `*.jsonl` file of `directory` in name order. A missing or empty directory: 0 cases."""
    if not directory.is_dir():
        return []
    cases: list[RegressionCase] = []
    for path in sorted(directory.glob("*.jsonl")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                cases.append(RegressionCase.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValidationError) as error:
                raise ValueError(
                    f"{path.name}:{number}: invalid regression case ({error})"
                ) from error
    return cases


def answer_text(answer: Answer) -> str:
    parts = [answer.summary, *[c.text for c in answer.claims], *[m.topic for m in answer.missing]]
    return "\n".join(parts).lower()


def check_case(case: RegressionCase, answer: Answer) -> str | None:
    """The reason the answer fails the case, or `None` when it passes."""
    if answer.abstained != case.expected.abstain:
        return f"abstained={answer.abstained}, expected {case.expected.abstain}"
    text = answer_text(answer)
    for needle in case.expected.must_contain:
        if needle.lower() not in text:
            return f"missing expected text {needle!r}"
    for needle in case.expected.must_not_contain:
        if needle.lower() in text:
            return f"contains forbidden text {needle!r}"
    return None


async def replay(
    cases: list[RegressionCase], *, adapter: Adapter, store: Store
) -> RegressionOutcome:
    outcome = RegressionOutcome(n_cases=len(cases))
    for case in cases:
        try:
            access = await store.access_for(case.user_id)
        except UnknownUserError:
            outcome.failures.append({"id": case.id, "reason": f"unknown user {case.user_id!r}"})
            continue
        answer = await adapter.ask(case.question, access=access, deal_id=case.deal_id)
        reason = check_case(case, answer)
        if reason is None:
            outcome.n_passed += 1
        else:
            outcome.failures.append({"id": case.id, "reason": reason})
    return outcome
