"""The `--split` option of the evaluation runner: dev for development, test for reporting."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from ainma.evaluation.adapter import Adapter
from ainma.evaluation.harness import evaluate_seed, in_split
from ainma.evaluation.run import build_parser
from ainma.evaluation.smoke import load_smoke_store, smoke_truth
from ainma.llm import build_mock_llm
from ainma.store import Store
from ainma.truth import split_of


@pytest.fixture
async def smoke_store() -> AsyncIterator[Store]:
    store = await load_smoke_store()
    yield store
    await store.close()


def test_default_split_is_test() -> None:
    assert build_parser().parse_args([]).split == "test"
    assert build_parser().parse_args(["--split", "dev"]).split == "dev"


def test_in_split_partitions_ids() -> None:
    ids = [f"q_{i:04d}" for i in range(200)]
    dev = {i for i in ids if in_split("dev", i)}
    test = {i for i in ids if in_split("test", i)}
    assert dev and test and not dev & test and dev | test == set(ids)
    assert all(in_split("both", i) for i in ids)
    assert all(split_of(i) == "dev" for i in dev)


async def test_dev_run_measures_only_dev_units(smoke_store: Store) -> None:
    truth = smoke_truth()
    adapter = Adapter(store=smoke_store, llm=build_mock_llm(), buyers=truth.buyers, use_real=False)
    result = await evaluate_seed("s", store=smoke_store, truth=truth, adapter=adapter, split="dev")
    dev = [q.id for q in truth.queries if split_of(q.id) == "dev"]
    assert result.query_ids == dev
    both = await evaluate_seed("s", store=smoke_store, truth=truth, adapter=adapter, split="both")
    assert both.query_ids == [q.id for q in truth.queries]
    labels = [lab for lab in truth.judge_labels if lab.split == "dev"]
    assert len(result.verifier.truth) == len(labels)


async def test_planted_cases_are_split_by_their_own_id(smoke_store: Store) -> None:
    truth = smoke_truth()
    adapter = Adapter(store=smoke_store, llm=build_mock_llm(), buyers=truth.buyers, use_real=False)
    counts: dict[str, int] = {}
    for split in ("dev", "test", "both"):
        result = await evaluate_seed(
            "s",
            store=smoke_store,
            truth=truth,
            adapter=adapter,
            split=split,  # type: ignore[arg-type]
        )
        units = result.contradiction
        counts[split] = len(units.planted) + len(units.controls) + len(units.flag_outcomes)
        counts[split + "_stale"] = len(units.stale_flagged)
    assert counts["dev"] + counts["test"] == counts["both"] == len(truth.contradictions)
    assert counts["dev_stale"] + counts["test_stale"] == counts["both_stale"] == len(truth.stale)
