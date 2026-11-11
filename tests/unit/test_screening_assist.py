# ruff: noqa: F811  (pytest fixtures imported from test_screening_run)
"""Model assisted stage 2 (D95): a model verdict counts only with a citation verified by code."""

from __future__ import annotations

import json
from typing import Any

from ainma.contracts import BuyerProfile, CriterionStatus, ScreeningFilters, ScreeningRequest
from ainma.llm import MockLLM, Usage
from ainma.llm.base import T
from ainma.screening import run_screening
from ainma.screening.assist import AssessEvidence, AssessResult
from ainma.store import SqliteStore
from tests.fixtures_biz.data_room import DEAL_ID
from tests.unit.test_screening_run import buyers, store  # noqa: F401  (fixtures)

REQUEST = ScreeningRequest(deal_id=DEAL_ID, filters=ScreeningFilters(geographies=["DACH"]))


class Scripted:
    """Answers `assess_criterion` with `met`, quoting the first evidence item honestly or not."""

    provider, model = "scripted", "scripted-1"

    def __init__(self, honest: bool) -> None:
        self.honest = honest
        self.calls = 0

    async def complete_json(
        self, *, task: str, system: str, user: str, schema: type[T], stage: str
    ) -> tuple[T, Usage]:
        self.calls += 1
        item = json.loads(user)["evidence"][0]
        quote = item["text"][:40] if self.honest else "a sentence that is in no document"
        result = AssessResult(
            status="met", rationale="scripted", evidence=[AssessEvidence(n=item["n"], quote=quote)]
        )
        return schema.model_validate(result.model_dump()), Usage(provider="s", model="s")


async def _run(db: SqliteStore, universe: list[BuyerProfile], llm: Any, assist: bool) -> Any:
    return await run_screening(
        REQUEST.model_copy(update={"llm_assist": assist}),
        store=db,
        access=await db.access_for("u_lead"),
        llm=llm,
        buyers=universe,
    )


def _statuses(result: Any) -> dict[tuple[str, str], Any]:
    return {(c.buyer.id, r.criterion_key): r for c in result.cards for r in c.results}


async def test_verified_model_verdicts_fill_unknowns_only(
    store: SqliteStore,
    buyers: list[BuyerProfile],
) -> None:
    base = _statuses(await _run(store, buyers, MockLLM({}), assist=False))
    model = Scripted(honest=True)
    assisted = _statuses(await _run(store, buyers, model, assist=True))
    assert model.calls > 0
    changed = [k for k in base if base[k].status != assisted[k].status]
    assert changed
    for key in changed:
        assert base[key].status is CriterionStatus.UNKNOWN  # rules' verdicts are never overridden
        result = assisted[key]
        assert result.status is CriterionStatus.MET and result.citations
        assert result.rationale.startswith("Model assessment (scripted scripted-1)")


async def test_unverified_model_verdicts_stay_unknown(
    store: SqliteStore,
    buyers: list[BuyerProfile],
) -> None:
    base = _statuses(await _run(store, buyers, MockLLM({}), assist=False))
    assisted = _statuses(await _run(store, buyers, Scripted(honest=False), assist=True))
    assert {k: v.status for k, v in base.items()} == {k: v.status for k, v in assisted.items()}
    noted = [v for k, v in assisted.items() if base[k].status is CriterionStatus.UNKNOWN]
    assert any("without verified evidence; not used" in v.rationale for v in noted)
