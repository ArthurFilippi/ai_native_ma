"""Blind label sample: stratification, blindness of the CSV, kappa scoring."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ainma.evaluation.adapter import Adapter
from ainma.evaluation.label_sample import (
    CSV_FIELDS,
    build_sample,
    read_human_labels,
    score_sample,
    stratified_sample,
    write_sample,
)
from ainma.evaluation.smoke import load_smoke_store, smoke_truth
from ainma.llm import build_mock_llm
from ainma.truth import JudgeLabel


def many_labels() -> list[JudgeLabel]:
    labels: list[JudgeLabel] = []
    strata = [
        ("supported", "none", 40),
        ("unsupported", "altered_number", 30),
        ("unsupported", "altered_period", 30),
        ("unsupported", "unrelated", 20),
        ("partial", "half_true", 20),
    ]
    for label, perturbation, count in strata:
        for i in range(count):
            labels.append(
                JudgeLabel.model_validate(
                    {
                        "id": f"{perturbation}_{i}",
                        "claim": f"claim {perturbation} {i}",
                        "chunk_id": "doc_cim_p2_00",
                        "label": label,
                        "perturbation": perturbation,
                        "split": "test",
                    }
                )
            )
    return labels


def test_sample_is_stratified_and_deterministic() -> None:
    labels = many_labels()
    one = stratified_sample(labels, 40, seed=1234)
    two = stratified_sample(labels, 40, seed=1234)
    assert [x.id for x in one] == [x.id for x in two]
    assert len(one) == 40
    # Round robin over 5 strata gives 8 of each.
    counts: dict[str, int] = {}
    for item in one:
        counts[item.perturbation] = counts.get(item.perturbation, 0) + 1
    assert set(counts.values()) == {8}
    other = stratified_sample(labels, 40, seed=99)
    assert [x.id for x in one] != [x.id for x in other]


def test_small_pool_is_taken_whole() -> None:
    assert len(stratified_sample(many_labels()[:5], 40, seed=1)) == 5


def test_csv_is_blind_and_key_is_separate(tmp_path: Path) -> None:
    truth = smoke_truth()
    passages = {label.chunk_id: f"passage of {label.chunk_id}" for label in truth.judge_labels}
    items = build_sample(truth.judge_labels, passages, seed=1234, size=8)
    csv_path, key_path = write_sample(items, tmp_path, seed=1234)
    text = csv_path.read_text(encoding="utf-8")
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert tuple(rows[0]) == CSV_FIELDS
    assert all(row["human_label"] == "" for row in rows)
    for forbidden in ("supported", "partial", "unsupported", "altered_", "half_true"):
        assert forbidden not in text.replace("human_label", "")
    assert [row["item_id"] for row in rows] == [f"h{i:02d}" for i in range(1, 9)]
    key = json.loads(key_path.read_text(encoding="utf-8"))
    assert {item["constructed_label"] for item in key["items"]} <= {
        "supported",
        "partial",
        "unsupported",
    }
    assert key["seed"] == 1234


async def test_scoring_reports_not_labelled_until_the_csv_is_filled(tmp_path: Path) -> None:
    truth = smoke_truth()
    passages = {label.chunk_id: "x" for label in truth.judge_labels}
    write_sample(build_sample(truth.judge_labels, passages, seed=1, size=8), tmp_path, seed=1)
    store = await load_smoke_store()
    adapter = Adapter(store=store, llm=build_mock_llm(), use_real=False)
    assert (await score_sample(tmp_path, adapter))["status"] == "not labelled yet"
    assert (await score_sample(tmp_path / "empty", adapter))["status"] == "not labelled yet"
    await store.close()


async def test_scoring_kappa_between_human_constructed_and_judge(tmp_path: Path) -> None:
    store = await load_smoke_store()
    truth = smoke_truth()
    passages = {}
    for label in truth.judge_labels:
        chunk = await store.get_chunk(label.chunk_id, truth.access())
        assert chunk is not None
        passages[label.chunk_id] = chunk.text
    items = build_sample(truth.judge_labels, passages, seed=3, size=10)
    csv_path, key_path = write_sample(items, tmp_path, seed=3)
    constructed = {item.item_id: item.constructed_label for item in items}
    # A human who agrees with the constructed labels on every item.
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["human_label"] = constructed[row["item_id"]].upper()  # case and spaces are normalised
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    adapter = Adapter(store=store, llm=build_mock_llm(), use_real=False)
    result = await score_sample(tmp_path, adapter)
    assert result["status"] == "scored"
    assert result["n_labelled"] == 10
    assert result["kappa_human_constructed"] == pytest.approx(1.0)
    assert result["weighted_kappa_human_constructed"] == pytest.approx(1.0)
    assert result["kappa_human_judge"] == pytest.approx(result["kappa_constructed_judge"])
    assert result["judge_components"] == "stub"
    assert key_path.exists()
    await store.close()


def test_unknown_human_label_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "s.csv"
    path.write_text("item_id,claim,passage,human_label\nh01,c,p,maybe\n", encoding="utf-8")
    with pytest.raises(ValueError, match="maybe"):
        read_human_labels(path)
