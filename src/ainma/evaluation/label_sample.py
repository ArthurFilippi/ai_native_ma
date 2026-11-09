"""Blind hand labelling of 40 (claim, passage) pairs (eval plan sections 2 and 8).

`python -m ainma.evaluation.label_sample --seed 1234` writes `eval/labels/label_sample.csv`
(claim, passage, an empty `human_label` column, nothing else) and the separate key
`label_sample_key.json`. The human fills the column with `supported`, `partial` or
`unsupported` without opening the key. `--score` then computes Cohen's kappa between the human
labels, the constructed labels and the judge, and writes `label_scores.json`, which the report
reads. This sample validates the constructed labels and the judge, it never tunes the system.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ainma.evaluation.adapter import Adapter
from ainma.evaluation.groundtruth import CorpusUnavailableError, TruthBundle, open_seed
from ainma.evaluation.metrics.agreement import JUDGE_LABELS, cohen_kappa, weighted_kappa
from ainma.llm import build_mock_llm
from ainma.store import SqliteStore, Store
from ainma.truth import JudgeLabel

SAMPLE_SIZE = 40
CSV_NAME = "label_sample.csv"
KEY_NAME = "label_sample_key.json"
SCORES_NAME = "label_scores.json"
CSV_FIELDS = ("item_id", "claim", "passage", "human_label")


@dataclass(frozen=True)
class SampleItem:
    item_id: str
    label_id: str
    claim: str
    passage: str
    constructed_label: str
    perturbation: str
    quote: str | None


def stratified_sample(labels: Sequence[JudgeLabel], size: int, seed: int) -> list[JudgeLabel]:
    """Round robin over the strata (constructed label, perturbation), each shuffled with the
    seed, so every stratum is represented before any is repeated."""
    rng = random.Random(seed)
    strata: dict[tuple[str, str], list[JudgeLabel]] = defaultdict(list)
    for label in sorted(labels, key=lambda item: item.id):
        strata[(label.label, label.perturbation)].append(label)
    queues = [strata[key] for key in sorted(strata)]
    for queue in queues:
        rng.shuffle(queue)
    chosen: list[JudgeLabel] = []
    while len(chosen) < size and any(queues):
        for queue in queues:
            if queue and len(chosen) < size:
                chosen.append(queue.pop())
    return chosen


def build_sample(
    labels: Sequence[JudgeLabel],
    passages: Mapping[str, str],
    *,
    seed: int,
    size: int = SAMPLE_SIZE,
) -> list[SampleItem]:
    """Stratified, shuffled items with neutral ids (the order carries no information)."""
    chosen = stratified_sample(labels, size, seed)
    random.Random(seed + 1).shuffle(chosen)
    return [
        SampleItem(
            item_id=f"h{index:02d}",
            label_id=label.id,
            claim=label.claim,
            passage=passages.get(label.chunk_id, ""),
            constructed_label=label.label,
            perturbation=label.perturbation,
            quote=label.quote,
        )
        for index, label in enumerate(chosen, start=1)
    ]


def write_sample(items: Sequence[SampleItem], out_dir: Path, *, seed: int) -> tuple[Path, Path]:
    """The CSV carries no constructed label and no judge output; the key file does."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path, key_path = out_dir / CSV_NAME, out_dir / KEY_NAME
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_FIELDS)
        for item in items:
            writer.writerow([item.item_id, item.claim, item.passage, ""])
    key = {"seed": seed, "items": [asdict(item) for item in items]}
    key_path.write_text(json.dumps(key, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return csv_path, key_path


def read_human_labels(csv_path: Path) -> dict[str, str]:
    """`item_id` to label for the filled rows. An unknown label is an error, not a skip."""
    out: dict[str, str] = {}
    with csv_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            value = (row.get("human_label") or "").strip().lower()
            if not value:
                continue
            if value not in JUDGE_LABELS:
                raise ValueError(f"{row['item_id']}: {value!r} is not one of {JUDGE_LABELS}")
            out[row["item_id"]] = value
    return out


async def score_sample(labels_dir: Path, adapter: Adapter) -> dict[str, Any]:
    """Kappa of human, constructed and judge labels on the filled rows."""
    csv_path, key_path = labels_dir / CSV_NAME, labels_dir / KEY_NAME
    if not csv_path.exists() or not key_path.exists():
        return {"status": "not labelled yet", "reason": "no label sample has been written"}
    human = read_human_labels(csv_path)
    if not human:
        return {"status": "not labelled yet", "n_labelled": 0}
    key = json.loads(key_path.read_text(encoding="utf-8"))
    rows = [item for item in key["items"] if item["item_id"] in human]
    h = [human[item["item_id"]] for item in rows]
    constructed = [item["constructed_label"] for item in rows]
    judged = [
        (await adapter.judge(item["claim"], item["passage"], item["quote"])).label for item in rows
    ]
    return {
        "status": "scored",
        "n_labelled": len(rows),
        "n_sample": len(key["items"]),
        "seed": key["seed"],
        "judge_components": adapter.modes["judge"],
        "kappa_human_constructed": cohen_kappa(h, constructed),
        "weighted_kappa_human_constructed": weighted_kappa(h, constructed),
        "kappa_human_judge": cohen_kappa(h, judged),
        "weighted_kappa_human_judge": weighted_kappa(h, judged),
        "kappa_constructed_judge": cohen_kappa(constructed, judged),
    }


async def passages_for(
    store: Store, truth: TruthBundle, labels: Sequence[JudgeLabel]
) -> dict[str, str]:
    access = truth.access()
    out: dict[str, str] = {}
    for label in labels:
        chunk = await store.get_chunk(label.chunk_id, access)
        if chunk is not None:
            out[label.chunk_id] = chunk.text
    return out


async def generate(seed: int, data_dir: Path, out_dir: Path) -> tuple[Path, Path]:
    store, truth = await open_seed(data_dir / str(seed))
    try:
        passages = await passages_for(store, truth, truth.judge_labels)
    finally:
        await store.close()
    items = build_sample(truth.judge_labels, passages, seed=seed)
    return write_sample(items, out_dir, seed=seed)


async def score(labels_dir: Path, *, force_stubs: bool) -> dict[str, Any]:
    store = await SqliteStore.open(":memory:")
    try:
        adapter = Adapter(store=store, llm=build_mock_llm(), use_real=not force_stubs)
        result = await score_sample(labels_dir, adapter)
    finally:
        await store.close()
    (labels_dir / SCORES_NAME).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ainma.evaluation.label_sample")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--score", action="store_true", help="score the filled CSV")
    parser.add_argument("--stub", action="store_true", help="force the stub judge when scoring")
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--out", type=Path, default=Path("eval/labels"))
    args = parser.parse_args(argv)
    if args.score:
        result = asyncio.run(score(args.out, force_stubs=args.stub))
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return 0
    try:
        csv_path, key_path = asyncio.run(generate(args.seed, args.data, args.out))
    except CorpusUnavailableError as error:
        sys.stderr.write(f"cannot write the label sample: {error}\n")
        return 2
    sys.stdout.write(
        f"wrote {csv_path} ({SAMPLE_SIZE} pairs, fill the human_label column) and {key_path}\n"
        "do not open the key file before labelling\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
