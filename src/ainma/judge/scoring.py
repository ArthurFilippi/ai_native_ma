"""Score logged answers for faithfulness and relevance.

- faithfulness: share of the SOURCED claims the judge labels `supported` from the claim text and
  its cited quotes (None when the answer has no sourced claim, for example an abstention);
- relevance: the judge's 0 to 1 rating of how directly the summary and claims address the
  question (not applied to abstentions).

Self preference: when the judge model is the model that wrote the answers the report says so.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from pydantic import BaseModel

from ainma.contracts import Answer, ClaimStatus
from ainma.llm.base import LLM
from ainma.llm.tasks import TASK_JUDGE
from ainma.pipeline import prompts
from ainma.pipeline.schemas import JudgeRequest, JudgeResult, RelevanceRequest, RelevanceResult

RELEVANCE_FLOOR = 0.3


class JudgedAnswer(BaseModel):
    answer_id: str
    question: str
    faithfulness: float | None
    relevance: float | None
    claim_labels: dict[str, str]
    flags: list[str]
    writer_model: str
    judge_model: str

    @property
    def flagged(self) -> bool:
        return bool(self.flags)

    @property
    def self_judged(self) -> bool:
        return self.writer_model == self.judge_model


async def judge_answer(
    answer: Answer, llm: LLM, *, relevance_floor: float = RELEVANCE_FLOOR
) -> JudgedAnswer:
    sourced = [c for c in answer.claims if c.status is ClaimStatus.SOURCED]

    async def label(claim_text: str, quotes: list[str]) -> str:
        request = JudgeRequest(claim=claim_text, quotes=quotes)
        result, _ = await llm.complete_json(
            task=TASK_JUDGE,
            system=prompts.JUDGE,
            user=request.model_dump_json(),
            schema=JudgeResult,
            stage="judge",
        )
        return result.label

    labels = await asyncio.gather(*(label(c.text, [q.quote for q in c.citations]) for c in sourced))
    claim_labels = {c.id: lab for c, lab in zip(sourced, labels, strict=True)}
    faithfulness = sum(lab == "supported" for lab in labels) / len(labels) if labels else None
    relevance: float | None = None
    if not answer.abstained:
        text = " ".join([answer.summary, *(c.text for c in answer.claims)])
        rated, _ = await llm.complete_json(
            task=TASK_JUDGE,
            system=prompts.RELEVANCE,
            user=RelevanceRequest(question=answer.question, answer=text).model_dump_json(),
            schema=RelevanceResult,
            stage="judge",
        )
        relevance = rated.score
    flags = [f"{lab}_claim:{cid}" for cid, lab in claim_labels.items() if lab != "supported"]
    if relevance is not None and relevance < relevance_floor:
        flags.append("low_relevance")
    return JudgedAnswer(
        answer_id=answer.id,
        question=answer.question,
        faithfulness=faithfulness,
        relevance=relevance,
        claim_labels=claim_labels,
        flags=flags,
        writer_model=answer.trace.model,
        judge_model=llm.model,
    )


async def judge_answers(answers: Sequence[Answer], llm: LLM) -> list[JudgedAnswer]:
    return [await judge_answer(a, llm) for a in answers]
