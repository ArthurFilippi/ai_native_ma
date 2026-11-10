"""Generate one seed: documents, manifest, news items and ground truth, written deterministically."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ainma.synth.common import Params
from ainma.synth.corpus import build_specs, manifest_entries, materialize, reset_dir
from ainma.synth.truthgen import Truth, build_truth

log = logging.getLogger(__name__)


def _dump(items: Any) -> str:
    def conv(x: Any) -> Any:
        if isinstance(x, BaseModel):
            return x.model_dump(mode="json", exclude={"tier"})
        if isinstance(x, list):
            return [conv(i) for i in x]
        if isinstance(x, dict):
            return {k: conv(v) for k, v in x.items()}
        return x

    return json.dumps(conv(items), indent=1, ensure_ascii=True) + "\n"


def write_truth(truth: Truth, seed_dir: Path) -> None:
    out = seed_dir / "truth"
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, Any] = {
        "deals": truth.deals,
        "users": truth.users,
        "buyers": truth.buyers,
        "facts": truth.facts,
        "queries": truth.queries,
        "unanswerable": truth.unanswerable,
        "contradictions": truth.contradictions,
        "stale": truth.stale,
        "kpi_truth": truth.kpi,
        "buyer_truth": truth.buyer_truth,
        "judge_labels": truth.judge,
        "params": truth.params,
        "aux": truth.aux,
    }
    for name, payload in files.items():
        (out / f"{name}.json").write_text(_dump(payload), encoding="utf-8")


def generate(seed: int, out_root: Path, *, paraphrase_rate: float | None = None, hard_negative_rate: float | None = None) -> Path:
    base = Params(seed=seed)
    params = Params(
        seed=seed,
        paraphrase_rate=base.paraphrase_rate if paraphrase_rate is None else paraphrase_rate,
        hard_negative_rate=base.hard_negative_rate if hard_negative_rate is None else hard_negative_rate,
    )
    seed_dir = Path(out_root) / str(seed)
    reset_dir(seed_dir)
    corpus = build_specs(params)
    materialize(corpus, seed_dir)
    (seed_dir / "manifest.json").write_text(_dump(manifest_entries(corpus)), encoding="utf-8")
    (seed_dir / "news").mkdir(parents=True, exist_ok=True)
    (seed_dir / "news" / "items.json").write_text(_dump(corpus.news), encoding="utf-8")
    truth = build_truth(corpus)
    write_truth(truth, seed_dir)
    log.info("seed %s: %d documents, %d facts, %d queries", seed, len(corpus.specs), len(truth.facts), len(truth.queries))
    return seed_dir
