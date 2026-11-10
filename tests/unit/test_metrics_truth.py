"""Reading the truth files of a seed and running the evaluation on a generated corpus layout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ainma.evaluation import groundtruth
from ainma.evaluation.groundtruth import CorpusUnavailableError, load_truth, open_seed
from ainma.evaluation.run import main
from ainma.evaluation.smoke import load_smoke_store, smoke_truth
from ainma.truth import GenerationParams


def write_seed(seed_dir: Path, *, drop: tuple[str, ...] = ()) -> None:
    truth = smoke_truth()
    folder = seed_dir / "truth"
    folder.mkdir(parents=True)
    rows: dict[str, Any] = {
        "deals": truth.deals,
        "buyers": truth.buyers,
        "facts": truth.facts,
        "queries": truth.queries,
        "unanswerable": truth.unanswerable,
        "contradictions": truth.contradictions,
        "stale": truth.stale,
        "kpi_truth": truth.kpi_truth,
        "buyer_truth": truth.buyer_truth,
        "judge_labels": truth.judge_labels,
    }
    for name, items in rows.items():
        if name not in drop:
            payload = [item.model_dump(mode="json") for item in items]
            (folder / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
    assert truth.users is not None
    (folder / "users.json").write_text(truth.users.model_dump_json(), encoding="utf-8")
    params = GenerationParams(
        seed=7, paraphrase_rate=0.3, hard_negative_rate=0.2, generator_version="t"
    )
    (folder / "params.json").write_text(params.model_dump_json(), encoding="utf-8")


def test_truth_round_trips_and_records_missing_files(tmp_path: Path) -> None:
    write_seed(tmp_path / "7", drop=("stale", "buyers"))
    bundle = load_truth(tmp_path / "7")
    original = smoke_truth()
    assert [q.id for q in bundle.queries] == [q.id for q in original.queries]
    assert [f.id for f in bundle.facts] == [f.id for f in original.facts]
    assert bundle.params is not None and bundle.params.seed == 7
    assert sorted(bundle.missing_files) == ["buyers.json", "stale.json"]
    assert bundle.stale == []
    assert bundle.access().allowed_deal_ids == frozenset({"deal_aurora", "deal_borealis"})


async def test_open_seed_needs_truth_and_a_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(CorpusUnavailableError, match="no truth directory"):
        await open_seed(tmp_path / "absent")
    write_seed(tmp_path / "7")
    monkeypatch.setattr(groundtruth, "resolve", lambda module, attribute: None)
    with pytest.raises(CorpusUnavailableError, match="load_corpus"):
        await open_seed(tmp_path / "7")


def test_full_run_on_a_generated_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for seed in ("7", "8"):
        write_seed(tmp_path / "data" / seed)

    async def loader(store: Any, seed_dir: Path) -> None:
        source = await load_smoke_store()
        for deal in smoke_truth().deals:
            access = smoke_truth().access()
            for meta in await source.list_documents(access, deal.id):
                page_count = meta.n_pages
                pages = [
                    await source.get_page(meta.id, n, access) or ""
                    for n in range(1, page_count + 1)
                ]
                await store.put_document(meta, pages)
                for chunk in [
                    c
                    for c in await source.candidates(access, deal_id=deal.id)
                    if c.document_id == meta.id
                ]:
                    await store.put_chunks([chunk])
        await source.close()

    monkeypatch.setattr(groundtruth, "resolve", lambda module, attribute: loader)
    out = tmp_path / "out"
    code = main(
        [
            "--seed-list",
            "7,8",
            "--stub",
            "--data",
            str(tmp_path / "data"),
            "--out",
            str(out),
            "--resamples",
            "100",
            "--regression",
            str(tmp_path / "no_regression"),
            "--labels",
            str(tmp_path / "no_labels"),
        ]
    )
    assert code == 0
    latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    assert latest["meta"]["seeds"] == ["7", "8"]
    assert latest["meta"]["smoke"] is False
    assert set(latest["summary"]["retrieval"]["per_seed"]) == {"7", "8"}
    # two seeds pooled: twice the test queries of one seed
    one_seed = len(
        [q for q in smoke_truth().queries if q.id in {"q_smoke_2", "q_smoke_4", "q_smoke_7"}]
    )
    assert latest["summary"]["retrieval"]["n_queries"] == 2 * one_seed
    assert latest["summary"]["generation_params"]["7"]["seed"] == 7
    report = (out / "RESULTS.md").read_text(encoding="utf-8")
    assert "SMOKE RUN" not in report
    assert "STUB COMPONENTS" in report
