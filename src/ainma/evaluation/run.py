"""Runner: `python -m ainma.evaluation.run --provider mock --seeds 5 [--smoke] [--out DIR]`.

Seeds: a single number from 1 to 5 means "the first N of 1234 1 2 3 4"; several numbers (or
`--seed-list`) name the seeds explicitly. For each seed the corpus is expected under
`data/synthetic/<seed>/` (see `python -m ainma.synth generate`). `--smoke` runs the whole flow on
a tiny built-in corpus with stubs and writes the same files quickly.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ainma.evaluation import smoke
from ainma.evaluation.adapter import Adapter
from ainma.evaluation.aggregate import BOOTSTRAP_SEED, sanitize, summarise
from ainma.evaluation.groundtruth import CorpusUnavailableError, TruthBundle, open_seed
from ainma.evaluation.harness import (
    SYSTEMS,
    TARGET_FALSE_ABSTENTION,
    TOP_K,
    EvalSplit,
    SeedResult,
    dev_support_scores,
    evaluate_seed,
)
from ainma.evaluation.metrics.abstention import choose_tau
from ainma.evaluation.regression import RegressionOutcome, load_cases, replay
from ainma.evaluation.report import RunMeta, render_report
from ainma.evaluation.stats import DEFAULT_RESAMPLES
from ainma.llm import LLM, build_llm, build_mock_llm
from ainma.settings import Settings
from ainma.store import Store

logger = logging.getLogger(__name__)

DEFAULT_SEEDS = (1234, 1, 2, 3, 4)
SMOKE_LABEL = "smoke"
LABEL_SCORES = "label_scores.json"


def parse_seeds(values: list[int], seed_list: str | None) -> list[int]:
    if seed_list:
        return [int(v) for v in seed_list.split(",") if v.strip()]
    if len(values) == 1 and 1 <= values[0] <= len(DEFAULT_SEEDS):
        return list(DEFAULT_SEEDS[: values[0]])
    return list(values)


def config_hash(config: dict[str, Any]) -> str:
    """Hash of everything that determines the numbers (never the date, commit or machine)."""
    canonical = json.dumps(sanitize(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def machine_description() -> str:
    return (
        f"{platform.system()} {platform.release()} {platform.machine()}, "
        f"Python {platform.python_version()}, {os.cpu_count()} CPUs"
    )


def git_commit() -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return done.stdout.strip() or "unknown"


def read_hand_labels(labels_dir: Path) -> dict[str, Any] | None:
    path = labels_dir / LABEL_SCORES
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def sweep_notes(adapter: Adapter) -> dict[str, str]:
    notes: dict[str, str] = {}
    for sweep in adapter.sweeps():
        if sweep.variants:
            notes[sweep.name] = "run"
        elif sweep.field is None:
            notes[sweep.name] = "the retrieval configuration exposes no field for it"
        else:
            notes[sweep.name] = f"field {sweep.field} has a shape the adapter cannot vary"
    return notes


async def _evaluate(
    label: str, store: Store, truth: TruthBundle, llm: LLM, *, use_real: bool, split: EvalSplit
) -> tuple[SeedResult, Adapter]:
    adapter = Adapter(store=store, llm=llm, buyers=truth.buyers, use_real=use_real)
    result = await evaluate_seed(
        label,
        store=store,
        truth=truth,
        adapter=adapter,
        split=split,
        frozen_tau=adapter.default_tau,
    )
    return result, adapter


async def run_evaluation(
    *,
    provider: str,
    seeds: list[int],
    smoke_run: bool,
    force_stubs: bool,
    out_dir: Path,
    data_dir: Path,
    regression_dir: Path,
    labels_dir: Path,
    n_resamples: int,
    split: EvalSplit = "test",
) -> Path:
    llm = build_mock_llm() if provider == "mock" else build_llm(Settings(llm_provider=provider))
    use_real = not (smoke_run or force_stubs)
    results: list[SeedResult] = []
    first_adapter: Adapter | None = None
    regression = RegressionOutcome()
    sources = [SMOKE_LABEL] if smoke_run else [str(s) for s in seeds]
    for label in sources:
        if smoke_run:
            store: Store = await smoke.load_smoke_store()
            truth = smoke.smoke_truth()
        else:
            store, truth = await open_seed(data_dir / label)
        try:
            result, adapter = await _evaluate(
                label, store, truth, llm, use_real=use_real, split=split
            )
            if first_adapter is None:
                first_adapter = adapter
                regression = await replay(load_cases(regression_dir), adapter=adapter, store=store)
        finally:
            await store.close()
        results.append(result)
    if first_adapter is None:
        raise ValueError("at least one seed is required")
    notes = sweep_notes(first_adapter)
    summary = summarise(
        results,
        provider=provider,
        sweep_notes=notes,
        hand_labels=read_hand_labels(labels_dir),
        n_resamples=n_resamples,
    )
    configuration = {
        "provider": provider,
        "model": llm.model,
        "seeds": sources,
        "modes": first_adapter.modes,
        "systems": list(SYSTEMS),
        "top_k": TOP_K,
        "target_false_abstention": TARGET_FALSE_ABSTENTION,
        "n_resamples": n_resamples,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "sweeps": notes,
        "backends": first_adapter.backends(),
        "adapter_config": first_adapter.config_snapshot(),
        "generation_params": {r.label: r.params for r in results},
        "smoke": smoke_run,
        **({"split": split} if split != "test" else {}),
    }
    meta = RunMeta(
        provider=provider,
        model=llm.model,
        seeds=sources,
        config_hash=config_hash(configuration),
        modes=first_adapter.modes,
        backends=first_adapter.backends(),
        dataset="tiny built-in fixture corpus (smoke)"
        if smoke_run
        else f"generated corpora under {data_dir.as_posix()}/<seed>/",
        smoke=smoke_run,
        n_resamples=n_resamples,
        split=split,
        abstain_basis=first_adapter.abstain_basis,
        date=datetime.now(UTC).strftime("%Y-%m-%d"),
        commit=git_commit(),
        machine=machine_description(),
        regression={
            "n_cases": regression.n_cases,
            "n_passed": regression.n_passed,
            "failures": regression.failures,
        },
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "RESULTS.md"
    report_path.write_text(render_report(summary, meta), encoding="utf-8")
    payload = {
        "meta": {
            **configuration,
            "config_hash": meta.config_hash,
            "date": meta.date,
            "git_commit": meta.commit,
            "machine": meta.machine,
            "label": "OFFLINE MOCK BASELINE, not an LLM result" if provider == "mock" else provider,
            "regression": meta.regression,
        },
        "summary": summary,
    }
    (out_dir / "latest.json").write_text(
        json.dumps(sanitize(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report_path


async def calibrate_tau(seeds: list[int], data_dir: Path, llm: LLM) -> str:
    """Pooled dev threshold of the given seeds, and the per seed values, as text.

    This is the command behind `pipeline.config.DEFAULT_TAU`: rerun it whenever the retrieval or
    the reranker changes, and copy the pooled value into `DEFAULT_TAU`.
    """
    pooled: list[float | None] = []
    lines: list[str] = []
    for seed in seeds:
        store, truth = await open_seed(data_dir / str(seed))
        try:
            adapter = Adapter(store=store, llm=llm, buyers=truth.buyers)
            scores = await dev_support_scores(adapter, truth)
        finally:
            await store.close()
        pooled += scores
        lines.append(
            f"seed {seed}: tau {choose_tau(scores, TARGET_FALSE_ABSTENTION):.6f} "
            f"(n={len(scores)} dev answerable queries)"
        )
    frozen = Adapter(store=store, llm=llm).default_tau
    lines.append(
        f"pooled dev tau: {choose_tau(pooled, TARGET_FALSE_ABSTENTION):.6f} "
        f"(n={len(pooled)}, target false abstention {TARGET_FALSE_ABSTENTION:.0%})"
    )
    lines.append(f"DEFAULT_TAU in pipeline/config.py: {frozen}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ainma.evaluation.run", description=__doc__)
    parser.add_argument("--provider", choices=["mock", "gemini", "openai"], default="mock")
    parser.add_argument("--seeds", type=int, nargs="+", default=[len(DEFAULT_SEEDS)])
    parser.add_argument("--seed-list", help="explicit comma separated seeds, overrides --seeds")
    parser.add_argument("--smoke", action="store_true", help="tiny built-in corpus, stubs only")
    parser.add_argument("--stub", action="store_true", help="force the stubs on a real corpus")
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--regression", type=Path, default=Path("eval/regression"))
    parser.add_argument("--labels", type=Path, default=Path("eval/labels"))
    parser.add_argument(
        "--split",
        choices=["dev", "test", "both"],
        default="test",
        help="units to measure; the default is the test split, dev is for development only",
    )
    parser.add_argument(
        "--calibrate-tau",
        action="store_true",
        help="print the pooled dev threshold and the per seed values, then exit",
    )
    parser.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    if args.calibrate_tau:
        seeds = parse_seeds(args.seeds, args.seed_list)
        llm = build_mock_llm()
        try:
            text = asyncio.run(calibrate_tau(seeds, args.data, llm))
        except CorpusUnavailableError as error:
            sys.stderr.write(f"cannot calibrate: {error}\n")
            return 2
        sys.stdout.write(text + "\n")
        return 0
    try:
        path = asyncio.run(
            run_evaluation(
                provider=args.provider,
                seeds=parse_seeds(args.seeds, args.seed_list),
                smoke_run=args.smoke,
                force_stubs=args.stub,
                out_dir=args.out,
                data_dir=args.data,
                regression_dir=args.regression,
                labels_dir=args.labels,
                n_resamples=args.resamples,
                split=args.split,
            )
        )
    except CorpusUnavailableError as error:
        sys.stderr.write(f"cannot run the evaluation: {error}\n")
        return 2
    sys.stdout.write(f"wrote {path} and {path.with_name('latest.json')}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
