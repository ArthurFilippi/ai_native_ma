"""KPI accuracy against the generated truth table (seed 1234), relative tolerance 0.5 percent.

The corpus is generated into a temporary directory (3 s), so the test needs no `make data`.
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
from ainma.synth.generate import generate
from ainma.truth import KpiTruth

REL_TOL = 0.005


@pytest.fixture(scope="module")
def seed_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate(1234, tmp_path_factory.mktemp("synthetic"))


async def test_kpi_accuracy_on_seed_1234(seed_dir: Path) -> None:
    loader = importlib.import_module("ainma.ingest.loader")
    truth = [
        KpiTruth.model_validate(t)
        for t in json.loads((seed_dir / "truth" / "kpi_truth.json").read_text("utf-8"))
    ]
    store = await SqliteStore.open(":memory:")
    try:
        await loader.load_corpus(store, seed_dir)
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
