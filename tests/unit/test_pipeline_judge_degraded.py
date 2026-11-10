"""The judge can be a different model from the writer, and a mock fallback marks the answer."""

from __future__ import annotations

from typing import Any

from ainma.llm import FallbackLLM, LLMError, MockLLM, Usage, build_mock_llm
from ainma.llm.base import T
from ainma.llm.providers.mock_tasks import default_mock_handlers
from ainma.llm.tasks import TASK_JUDGE
from ainma.pipeline import PipelineConfig, ask
from ainma.store import SqliteStore

CONFIG = PipelineConfig(answers_log=None)


class Recording:
    """A mock that records the tasks it served, under a distinct name."""

    def __init__(self, provider: str, model: str) -> None:
        self.provider, self.model = provider, model
        self.tasks: list[str] = []
        self._inner = MockLLM(default_mock_handlers())

    async def complete_json(
        self, *, task: str, system: str, user: str, schema: type[T], stage: str
    ) -> tuple[T, Usage]:
        self.tasks.append(task)
        parsed, usage = await self._inner.complete_json(
            task=task, system=system, user=user, schema=schema, stage=stage
        )
        return parsed, usage.model_copy(update={"provider": self.provider, "model": self.model})


class Broken:
    provider, model = "gemini", "gemini-2.5-flash"

    async def complete_json(self, **_: Any) -> Any:
        raise LLMError("gemini: request failed (HTTP 503)")


async def test_judge_calls_go_to_the_judge_model_and_the_trace_names_both(
    tiny_store: SqliteStore,
) -> None:
    writer = Recording("writer-provider", "writer-model")
    judge = Recording("judge-provider", "judge-model")
    access = await tiny_store.access_for("u_analyst")
    answer = await ask(
        "What was FY2024 revenue?",
        store=tiny_store,
        access=access,
        deal_id="deal_aurora",
        llm=writer,
        judge_llm=judge,
        config=CONFIG,
    )
    assert judge.tasks and set(judge.tasks) == {TASK_JUDGE}
    assert TASK_JUDGE not in writer.tasks
    assert (answer.trace.model, answer.trace.judge_model) == ("writer-model", "judge-model")
    assert answer.trace.judge_provider == "judge-provider"
    assert not answer.degraded


async def test_without_a_judge_the_trace_says_the_writer_judged(tiny_store: SqliteStore) -> None:
    access = await tiny_store.access_for("u_analyst")
    answer = await ask(
        "What was FY2024 revenue?",
        store=tiny_store,
        access=access,
        deal_id="deal_aurora",
        llm=build_mock_llm(),
        config=CONFIG,
    )
    assert answer.trace.judge_model == answer.trace.model


async def test_mock_fallback_marks_the_answer_degraded(tiny_store: SqliteStore) -> None:
    llm = FallbackLLM(Broken(), build_mock_llm())
    access = await tiny_store.access_for("u_analyst")
    answer = await ask(
        "What was FY2024 revenue?",
        store=tiny_store,
        access=access,
        deal_id="deal_aurora",
        llm=llm,
        config=CONFIG,
    )
    assert answer.degraded
    assert answer.degraded_reason and "gemini" in answer.degraded_reason
    assert "mock" in answer.degraded_reason
