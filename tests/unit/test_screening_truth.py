"""Screening against the generated buyer truth (seed 1234). Skipped until the corpus exists.

Only the criteria where the system commits to `met` or `not_met` are compared; an `unknown` is
the honest answer and is reported by `make eval`, not penalised here.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from ainma.contracts import CriterionStatus, ScreeningRequest
from ainma.llm import MockLLM
from ainma.screening import load_buyers, run_screening
from ainma.store import SqliteStore
from ainma.truth import BuyerTruth

SEED_DIR = Path(__file__).parents[2] / "data" / "synthetic" / "1234"


async def test_decided_criteria_agree_with_the_buyer_truth() -> None:
    if not (SEED_DIR / "truth" / "buyer_truth.json").exists():
        pytest.skip("seed 1234 corpus not generated yet (data agent)")
    try:
        loader = importlib.import_module("ainma.ingest.loader")
        importlib.import_module("ainma.retrieval")
    except ImportError:
        pytest.skip("ingest or retrieval not merged yet")
    truth = [
        BuyerTruth.model_validate(t)
        for t in json.loads((SEED_DIR / "truth" / "buyer_truth.json").read_text("utf-8"))
    ]
    store = await SqliteStore.open(":memory:")
    try:
        await loader.load_corpus(store, SEED_DIR)
        access = await store.access_for("u_lead")
        result = await run_screening(
            ScreeningRequest(deal_id=truth[0].deal_id, stage2_top_n=50),
            store=store,
            access=access,
            llm=MockLLM({}),
            buyers=load_buyers(SEED_DIR),
        )
    finally:
        await store.close()
    got = {(c.buyer.id, r.criterion_key): r.status for c in result.cards for r in c.results}
    decided = [
        (t, got[(t.buyer_id, t.criterion_key)])
        for t in truth
        if got.get((t.buyer_id, t.criterion_key), CriterionStatus.UNKNOWN)
        is not CriterionStatus.UNKNOWN
        and t.status is not CriterionStatus.UNKNOWN
    ]
    assert decided, "no criterion was decided"
    agreement = sum(t.status is status for t, status in decided) / len(decided)
    assert agreement >= 0.5, f"agreement {agreement:.2f} over {len(decided)} decided criteria"
