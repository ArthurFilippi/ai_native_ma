"""KPI accuracy against the generated truth table (seed 1234), relative tolerance 0.5 percent.

Skipped until the `data` and `core` agents are merged and `make data` has produced the corpus.
The gates are provisional smoke gates; the numbers that count come from `make eval`.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from ainma.kpi import extract_kpis
from ainma.kpi.parse import value_in_quote
from ainma.llm import MockLLM
from ainma.store import SqliteStore
from ainma.truth import KpiTruth

SEED_DIR = Path(__file__).parents[2] / "data" / "synthetic" / "1234"
REL_TOL = 0.005


def _require_corpus() -> None:
    if not (SEED_DIR / "truth" / "kpi_truth.json").exists():
        pytest.skip("seed 1234 corpus not generated yet (data agent)")
    for module in ("ainma.ingest.loader", "ainma.retrieval"):
        try:
            importlib.import_module(module)
        except ImportError:
            pytest.skip(f"{module} not merged yet")


async def test_kpi_accuracy_on_seed_1234() -> None:
    _require_corpus()
    loader = importlib.import_module("ainma.ingest.loader")
    truth = [
        KpiTruth.model_validate(t)
        for t in json.loads((SEED_DIR / "truth" / "kpi_truth.json").read_text("utf-8"))
    ]
    store = await SqliteStore.open(":memory:")
    try:
        await loader.load_corpus(store, SEED_DIR)
        deal_id = truth[0].deal_id
        access = await store.access_for("u_lead")
        values = await extract_kpis(
            deal_id,
            store=store,
            access=access,
            llm=MockLLM({}),
            periods=sorted({t.period for t in truth}),
            kpi_ids=sorted({t.kpi_id for t in truth}),
        )
    finally:
        await store.close()
    got = {(v.kpi_id, v.period): v for v in values}
    correct = wrong = missing = 0
    for item in truth:
        value = got[(item.kpi_id, item.period)]
        if value.value is None:
            missing += 1
        elif abs(value.value - item.value) <= REL_TOL * abs(item.value):
            correct += 1
        else:
            wrong += 1
        if value.status == "sourced":
            assert value_in_quote(value.value or 0.0, value.citations[0].quote)
    answered = correct + wrong
    assert answered, "no KPI value was extracted at all"
    assert wrong / answered <= 0.05, f"wrong-value rate {wrong}/{answered}"
    assert correct / len(truth) >= 0.5, f"accuracy {correct}/{len(truth)}, missing {missing}"
