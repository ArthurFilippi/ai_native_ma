"""One-glance confidence (D97): rules on hand built answers, and the pipeline fills it."""

from __future__ import annotations

from datetime import date

from ainma.contracts import (
    Answer,
    Citation,
    Claim,
    ClaimStatus,
    Contradiction,
    ContradictionSide,
    DocType,
    Flag,
    MissingInfo,
    SourceTier,
    Trace,
)
from ainma.llm import build_mock_llm
from ainma.pipeline import PipelineConfig, ask
from ainma.pipeline.confidence import answer_confidence
from ainma.store import SqliteStore


def _cite(doc: str, tier: int) -> Citation:
    return Citation(
        chunk_id=f"ch_{doc}", document_id=doc, doc_title=doc, doc_type=DocType.DEAL_DOCUMENT,
        tier=SourceTier(tier), published_on=date(2025, 1, 1), page=1, char_start=0, char_end=5,
        quote="quote",
    )  # fmt: skip


def _answer(*claims: Claim, **extra: object) -> Answer:
    return Answer(
        id="a", deal_id="d", user_id="u", question="q", summary="s", claims=list(claims),
        trace=Trace(provider="mock", model="m"), **extra,  # type: ignore[arg-type]
    )  # fmt: skip


def _claim(*cites: Citation, flags: list[Flag] | None = None) -> Claim:
    return Claim(
        id="c1", text="x", status=ClaimStatus.SOURCED, citations=list(cites), flags=flags or []
    )


def test_levels() -> None:
    assert answer_confidence(_answer(_claim(_cite("a", 2), _cite("b", 2))))[0] == "high"
    assert answer_confidence(_answer(_claim(_cite("a", 1))))[0] == "high"
    assert answer_confidence(_answer(_claim(_cite("a", 2))))[0] == "medium"
    assert answer_confidence(_answer(_claim(_cite("a", 4))))[0] == "low"
    assert answer_confidence(_answer(_claim(_cite("a", 1), flags=[Flag.UNVERIFIED])))[0] == "low"
    stale = _answer(_claim(_cite("a", 1), flags=[Flag.STALE]))
    assert answer_confidence(stale) == (
        "medium",
        "Medium: a source is old, superseded or withdrawn.",
    )
    missing = _answer(_claim(_cite("a", 1)), missing=[MissingInfo(topic="t", reason="not_found")])
    assert answer_confidence(missing)[0] == "medium"
    side = ContradictionSide(label="x", claim_id="c1", citations=[_cite("a", 1)], strength=0.5)
    disagree = _answer(
        _claim(_cite("a", 1)),
        contradictions=[Contradiction(id="k", subject="s", sides=[side, side])],
    )
    level, reason = answer_confidence(disagree)
    assert level == "medium" and reason and "disagree" in reason
    abstained = _answer(abstained=True)
    assert answer_confidence(abstained) == (None, None)


async def test_the_pipeline_fills_the_level(tiny_store: SqliteStore) -> None:
    access = await tiny_store.access_for("u_analyst")
    answer = await ask(
        "What was FY2024 revenue?",
        store=tiny_store,
        access=access,
        deal_id="deal_aurora",
        llm=build_mock_llm(),
        config=PipelineConfig(answers_log=None),
    )
    assert answer.confidence in {"high", "medium", "low"} and answer.confidence_reason
