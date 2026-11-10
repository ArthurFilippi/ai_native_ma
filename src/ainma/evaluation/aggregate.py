"""Pool the units of all seeds, put 95 percent intervals on them and build the summary.

Pooling rule: every seed is an independent generated dataset, so the unit of resampling is a
(seed, query), (seed, claim) or (seed, KPI cell). Alongside every pooled interval the summary
keeps the per seed values and their mean and standard deviation across seeds.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from itertools import combinations
from typing import Any

import numpy as np

from ainma.evaluation.harness import RETRIEVAL_METRICS, SYSTEMS, SeedResult
from ainma.evaluation.metrics.abstention import (
    NO_EVIDENCE,
    choose_tau,
    rates_at_tau,
    threshold_curve,
)
from ainma.evaluation.metrics.agreement import (
    JUDGE_LABELS,
    IntArray,
    confusion_matrix,
    encode,
    kappa_from_codes,
)
from ainma.evaluation.metrics.contradiction import contradiction_scores
from ainma.evaluation.metrics.kpi import kpi_scores
from ainma.evaluation.metrics.performance import mean_cost, percentile
from ainma.evaluation.metrics.screening import screening_scores
from ainma.evaluation.metrics.verifier import recall_by_group
from ainma.evaluation.stats import (
    DEFAULT_RESAMPLES,
    FloatArray,
    Interval,
    Sample,
    bootstrap_function,
    bootstrap_interval,
    bootstrap_weights,
    count_sample,
    holm_adjust,
    mean_sample,
    paired_bootstrap,
)

BOOTSTRAP_SEED = 20240611
PAIRWISE_SHOWN = ("ndcg@10", "recall@10", "mrr")
CURVE_POINTS = 12
SWEEP_METRICS = ("ndcg@10", "recall@10", "mrr")
Summary = dict[str, Any]


def iv(interval: Interval) -> dict[str, float | None]:
    return {"estimate": interval.estimate, "lo": interval.lo, "hi": interval.hi}


def across(values: Sequence[float | None]) -> dict[str, float | int | None]:
    """Mean and sample standard deviation of per seed values."""
    known = [v for v in values if v is not None]
    if not known:
        return {"mean": None, "sd": None, "n": 0}
    sd = float(np.std(known, ddof=1)) if len(known) > 1 else None
    return {"mean": float(np.mean(known)), "sd": sd, "n": len(known)}


def sanitize(value: Any) -> Any:
    """JSON safe copy: numpy scalars to Python, non finite floats to `None`."""
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [sanitize(v) for v in value]
    if isinstance(value, np.generic):
        return sanitize(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _bools(flags: Sequence[bool]) -> Sample:
    return mean_sample([1.0 if f else 0.0 for f in flags])


def _est(sample: Sample) -> float | None:
    return sample.estimate()


class Pooler:
    """Resampling weights are drawn once per unit set so every comparison on those units shares
    the same resamples."""

    def __init__(self, n_resamples: int, seed: int) -> None:
        self.n_resamples = n_resamples
        self.seed = seed

    def weights(self, n: int, offset: int, clusters: Sequence[str] | None = None) -> FloatArray:
        return bootstrap_weights(
            n, seed=self.seed + offset, n_resamples=self.n_resamples, clusters=clusters
        )


# ---------------------------------------------------------------------------- retrieval


def _retrieval(results: Sequence[SeedResult], pool: Pooler, notes: dict[str, str]) -> Summary:
    n = sum(len(r.query_ids) for r in results)
    clusters = [f"{r.label}:{c}" for r in results for c in r.clusters]
    plain = pool.weights(n, 1)
    clustered = pool.weights(n, 2, clusters)
    pooled = {
        m: {s: [v for r in results for v in r.retrieval[m][s]] for s in SYSTEMS}
        for m in RETRIEVAL_METRICS
    }
    out: Summary = {
        "n_queries": n,
        "systems": {},
        "pairwise": {},
        "per_seed": {},
        "across_seeds": {},
    }
    samples = {m: {s: mean_sample(pooled[m][s]) for s in SYSTEMS} for m in RETRIEVAL_METRICS}
    for system in SYSTEMS:
        out["systems"][system] = {
            m: iv(bootstrap_interval(samples[m][system], plain)) for m in RETRIEVAL_METRICS
        }
        out["across_seeds"][system] = {
            m: across([_est(mean_sample(r.retrieval[m][system])) for r in results])
            for m in RETRIEVAL_METRICS
        }
    for r in results:
        out["per_seed"][r.label] = {
            "n": len(r.query_ids),
            **{
                s: {m: _est(mean_sample(r.retrieval[m][s])) for m in RETRIEVAL_METRICS}
                for s in SYSTEMS
            },
        }
    for metric in RETRIEVAL_METRICS:
        rows: list[dict[str, Any]] = []
        for earlier, later in combinations(SYSTEMS, 2):
            plain_cmp = paired_bootstrap(samples[metric][later], samples[metric][earlier], plain)
            cluster_cmp = paired_bootstrap(
                samples[metric][later], samples[metric][earlier], clustered
            )
            rows.append(
                {
                    "pair": f"{later} - {earlier}",
                    "diff": iv(plain_cmp.diff),
                    "share_positive": plain_cmp.share_positive,
                    "p_value": plain_cmp.p_value,
                    "cluster_diff": iv(cluster_cmp.diff),
                }
            )
        adjusted = holm_adjust(
            {row["pair"]: row["p_value"] for row in rows if row["p_value"] is not None}
        )
        for row in rows:
            row["p_holm"] = adjusted.get(row["pair"])
        out["pairwise"][metric] = rows
    out["sweeps"] = _sweeps(results, samples, plain, notes)
    return out


def _sweeps(
    results: Sequence[SeedResult],
    samples: dict[str, dict[str, Sample]],
    plain: FloatArray,
    notes: dict[str, str],
) -> Summary:
    out: Summary = {}
    for name, note in notes.items():
        variants: dict[str, dict[str, Any]] = {}
        labels = sorted({label for r in results for label in r.sweeps.get(name, {})})
        for label in labels:
            variants[label] = {}
            for metric in SWEEP_METRICS:
                values = [v for r in results for v in r.sweeps[name][label][metric][label]]
                sample = mean_sample(values)
                cmp = paired_bootstrap(sample, samples[metric]["A5"], plain)
                variants[label][metric] = {
                    "value": iv(cmp.a),
                    "diff_vs_default": iv(cmp.diff),
                    "share_positive": cmp.share_positive,
                }
        out[name] = {"status": note if not variants else "run", "note": note, "variants": variants}
    return out


# ---------------------------------------------------------------------------- citations


def _citation(results: Sequence[SeedResult], pool: Pooler) -> Summary:
    def column(setting: str, name: str) -> list[int]:
        return [v for r in results for v in getattr(r.citation[setting], name)]

    n = len(column("on", "n_claims"))
    weights = pool.weights(n, 3)
    metrics = {
        "citation_precision": ("n_correct", "n_claims"),
        "citation_recall": ("n_covered", "n_facts"),
        "unsupported_claim_rate": ("n_unsupported", "n_claims"),
    }
    out: Summary = {"n_queries": n, "metrics": {}, "per_seed": {}}
    for key, (num, den) in metrics.items():
        on = count_sample(column("on", num), column("on", den))
        off = count_sample(column("off", num), column("off", den))
        cmp = paired_bootstrap(on, off, weights)
        out["metrics"][key] = {
            "verifier_on": iv(cmp.a),
            "verifier_off": iv(cmp.b),
            "difference": iv(cmp.diff),
            "share_positive": cmp.share_positive,
        }
    on_claims, off_claims = sum(column("on", "n_claims")), sum(column("off", "n_claims"))
    out["claims_with_verifier"] = on_claims
    out["claims_without_verifier"] = off_claims
    out["dropped_claims"] = off_claims - on_claims
    for r in results:
        row: Summary = {}
        for setting in ("on", "off"):
            units = r.citation[setting]
            row[setting] = {
                key: _est(count_sample(getattr(units, num), getattr(units, den)))
                for key, (num, den) in metrics.items()
            }
        out["per_seed"][r.label] = row
    out["across_seeds"] = {
        setting: {
            key: across([out["per_seed"][r.label][setting][key] for r in results])
            for key in metrics
        }
        for setting in ("on", "off")
    }
    return out


# ---------------------------------------------------------------------------- verifier, judge


def _verifier(results: Sequence[SeedResult], pool: Pooler) -> Summary:
    truth = [t for r in results for t in r.verifier.truth]
    flagged = [f for r in results for f in r.verifier.flagged]
    groups = [g for r in results for g in r.verifier.perturbation]
    n = len(truth)
    weights = pool.weights(n, 4)
    positive = np.array([t != "supported" for t in truth], dtype=np.float64)
    flags = np.array(flagged, dtype=np.float64)
    hit = positive * flags

    def sample(num: FloatArray, den: FloatArray) -> Sample:
        return Sample(num, den)

    selectors = {
        "recall_not_supported": sample(hit, positive),
        "recall_unsupported": sample(
            hit * np.array([t == "unsupported" for t in truth]),
            np.array([t == "unsupported" for t in truth], dtype=np.float64),
        ),
        "recall_partial": sample(
            hit * np.array([t == "partial" for t in truth]),
            np.array([t == "partial" for t in truth], dtype=np.float64),
        ),
        "precision": sample(hit, flags),
        "false_flag_rate": sample(flags * (1 - positive), (1 - positive)),
    }
    return {
        "n_claims": n,
        "metrics": {k: iv(bootstrap_interval(s, weights)) for k, s in selectors.items()},
        "recall_by_perturbation": recall_by_group(groups, truth, flagged),
        "per_seed": {
            r.label: {
                "recall_not_supported": _recall(r.verifier.truth, r.verifier.flagged),
                "n": len(r.verifier.truth),
            }
            for r in results
        },
    }


def _recall(truth: Sequence[str], flagged: Sequence[bool]) -> float | None:
    flags = [f for t, f in zip(truth, flagged, strict=True) if t != "supported"]
    return sum(flags) / len(flags) if flags else None


def _kappa_interval(
    a: IntArray, b: IntArray, *, weighted: bool, seed: int, n_resamples: int
) -> Interval:
    def statistic(idx: IntArray) -> float | None:
        return kappa_from_codes(a[idx], b[idx], len(JUDGE_LABELS), weighted=weighted)

    return bootstrap_function(len(a), statistic, seed=seed, n_resamples=n_resamples)


def _judge(
    results: Sequence[SeedResult], pool: Pooler, hand_labels: dict[str, Any] | None
) -> Summary:
    truth = [t for r in results for t in r.verifier.truth]
    judged = [j for r in results for j in r.verifier.judge]
    out: Summary = {"n_claims": len(truth), "labels": list(JUDGE_LABELS)}
    if truth:
        a, b = encode(truth, JUDGE_LABELS), encode(judged, JUDGE_LABELS)
        out["kappa"] = iv(
            _kappa_interval(a, b, weighted=False, seed=pool.seed + 5, n_resamples=pool.n_resamples)
        )
        out["weighted_kappa"] = iv(
            _kappa_interval(a, b, weighted=True, seed=pool.seed + 6, n_resamples=pool.n_resamples)
        )
        out["confusion"] = confusion_matrix(truth, judged, JUDGE_LABELS)
    out["per_seed"] = {
        r.label: kappa_from_codes(
            encode(r.verifier.truth, JUDGE_LABELS),
            encode(r.verifier.judge, JUDGE_LABELS),
            len(JUDGE_LABELS),
        )
        if r.verifier.truth
        else None
        for r in results
    }
    out["hand_labels"] = hand_labels if hand_labels is not None else {"status": "not labelled yet"}
    return out


# ---------------------------------------------------------------------------- abstention


def _curve_subset(points: list[Any]) -> list[Any]:
    if len(points) <= CURVE_POINTS:
        return points
    picks = sorted({round(i * (len(points) - 1) / (CURVE_POINTS - 1)) for i in range(CURVE_POINTS)})
    return [points[i] for i in picks]


def _abstention(results: Sequence[SeedResult], pool: Pooler) -> Summary:
    per_seed: Summary = {}
    score_unans: list[bool] = []
    score_ans: list[bool] = []
    hard_flags: list[bool] = []
    pooled_ans: list[float | None] = []
    pooled_unans: list[float | None] = []
    pooled_dev: list[float | None] = []
    target = 0.0
    e2e_ans = [f for r in results if r.abstention for f in r.abstention.e2e_answerable]
    e2e_unans = [f for r in results if r.abstention for f in r.abstention.e2e_unanswerable]
    for r in results:
        a = r.abstention
        if a is None:
            continue
        at_tau = rates_at_tau(a.tau, a.test_answerable, a.test_unanswerable)
        dev = rates_at_tau(a.tau, a.dev_answerable, a.dev_unanswerable)
        score_ans += [(NO_EVIDENCE if s is None else s) < a.tau for s in a.test_answerable]
        score_unans += [(NO_EVIDENCE if s is None else s) < a.tau for s in a.test_unanswerable]
        hard_flags += a.test_unanswerable_hard
        pooled_ans += a.test_answerable
        pooled_unans += a.test_unanswerable
        pooled_dev += a.dev_answerable
        target = a.target
        per_seed[r.label] = {
            "tau": a.tau,
            "dev_tau": a.dev_tau,
            "target_false_abstention": a.target,
            "dev_false_abstention": dev.false_abstention_rate,
            "n_dev_answerable": len(a.dev_answerable),
            "n_test_answerable": len(a.test_answerable),
            "n_test_unanswerable": len(a.test_unanswerable),
            "correct_abstention": at_tau.correct_abstention_rate,
            "false_abstention": at_tau.false_abstention_rate,
            "precision": at_tau.precision,
            "e2e_correct_abstention": _share(a.e2e_unanswerable),
            "e2e_false_abstention": _share(a.e2e_answerable),
        }
    w_unans = pool.weights(len(score_unans), 7)
    w_ans = pool.weights(len(score_ans), 8)
    hard = _by_hardness(score_unans, hard_flags, True)
    easy = _by_hardness(score_unans, hard_flags, False)
    applied = {row["tau"] for row in per_seed.values()}
    out: Summary = {
        # abstentions of the full pipeline that were on unanswerable questions
        "end_to_end_precision": (
            sum(e2e_unans) / (sum(e2e_unans) + sum(e2e_ans))
            if sum(e2e_unans) + sum(e2e_ans)
            else None
        ),
        # the threshold the test split was evaluated at (one value when it is frozen), and the
        # one a recalibration on the pooled dev queries of this run would give: drift is visible
        "frozen_tau": applied.pop() if len(applied) == 1 else None,
        "pooled_dev_tau": choose_tau(pooled_dev, target) if pooled_dev and target else None,
        "per_seed": per_seed,
        "across_seeds": {
            key: across([row.get(key) for row in per_seed.values()])
            for key in ("correct_abstention", "false_abstention", "precision")
        },
        "score_based": {
            "correct_abstention": iv(bootstrap_interval(_bools(score_unans), w_unans)),
            "false_abstention": iv(bootstrap_interval(_bools(score_ans), w_ans)),
        },
        "end_to_end": {
            "correct_abstention": iv(
                bootstrap_interval(_bools(e2e_unans), pool.weights(len(e2e_unans), 9))
            ),
            "false_abstention": iv(
                bootstrap_interval(_bools(e2e_ans), pool.weights(len(e2e_ans), 10))
            ),
        },
        "hard_unanswerable": {"n": len(hard), "correct_abstention": _share(hard)},
        "easy_unanswerable": {"n": len(easy), "correct_abstention": _share(easy)},
        "curve": [
            {
                "tau": p.tau,
                "correct_abstention": p.correct_abstention_rate,
                "false_abstention": p.false_abstention_rate,
                "precision": p.precision,
            }
            for p in _curve_subset(threshold_curve(pooled_ans, pooled_unans))
        ],
    }
    return out


def _by_hardness(flags: list[bool], hard: list[bool], want_hard: bool) -> list[bool]:
    return [f for f, h in zip(flags, hard, strict=True) if h == want_hard]


def _share(flags: Sequence[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


# ---------------------------------------------------------------------------- contradictions


def _contradiction(results: Sequence[SeedResult], pool: Pooler) -> Summary:
    planted = [f for r in results for f in r.contradiction.planted]
    controls = [f for r in results for f in r.contradiction.controls]
    both = [f for r in results for f in r.contradiction.both_sides_cited]
    stronger = [f for r in results for f in r.contradiction.stronger_agrees]
    outcomes = [o for r in results for o in r.contradiction.flag_outcomes]
    stale = [f for r in results for f in r.contradiction.stale_flagged]
    flag = np.array(planted + controls, dtype=bool)
    is_planted = np.array([True] * len(planted) + [False] * len(controls), dtype=bool)

    def f1_stat(idx: IntArray) -> float | None:
        tp = int((flag[idx] & is_planted[idx]).sum())
        fp = int((flag[idx] & ~is_planted[idx]).sum())
        fn = int((~flag[idx] & is_planted[idx]).sum())
        return 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else None

    def precision_stat(idx: IntArray) -> float | None:
        tp = int((flag[idx] & is_planted[idx]).sum())
        fp = int((flag[idx] & ~is_planted[idx]).sum())
        return tp / (tp + fp) if (tp + fp) else None

    scores = contradiction_scores(planted, controls)
    n_total = len(flag)
    out: Summary = {
        "n_planted": len(planted),
        "n_controls": len(controls),
        "recall": iv(bootstrap_interval(_bools(planted), pool.weights(len(planted), 11))),
        "false_positive_rate": iv(
            bootstrap_interval(_bools(controls), pool.weights(len(controls), 12))
        ),
        "precision": iv(
            bootstrap_function(
                n_total, precision_stat, seed=pool.seed + 13, n_resamples=pool.n_resamples
            )
        )
        if n_total
        else None,
        "f1": iv(
            bootstrap_function(n_total, f1_stat, seed=pool.seed + 14, n_resamples=pool.n_resamples)
        )
        if n_total
        else None,
        "point": {"recall": scores.recall, "fpr": scores.false_positive_rate, "f1": scores.f1},
        "completeness": {"n_detected": len(both), "both_sides_cited": _share(both)},
        "stronger_side_agreement": {"n": len(stronger), "share": _share(stronger)},
        "superseded_withdrawn": {
            "n": len(outcomes),
            **{
                key: sum(1 for o in outcomes if o == key)
                for key in ("flagged", "contradicted_instead", "unflagged", "not_surfaced")
            },
        },
        "stale": {"n": len(stale), "flagged": _share(stale)},
        "per_seed": {
            r.label: {
                "recall": _share(r.contradiction.planted),
                "false_positive_rate": _share(r.contradiction.controls),
                "f1": contradiction_scores(r.contradiction.planted, r.contradiction.controls).f1,
            }
            for r in results
        },
    }
    return out


# ---------------------------------------------------------------------------- KPI, screening


def _kpi(results: Sequence[SeedResult], pool: Pooler) -> Summary:
    cells = [c for r in results for c in r.kpi]
    n = len(cells)
    weights = pool.weights(n, 15)
    correct = np.array(
        [c.outcome.value is not None and kpi_scores([c.outcome]).accuracy == 1.0 for c in cells],
        dtype=np.float64,
    )
    answered = np.array([c.outcome.value is not None for c in cells], dtype=np.float64)
    valid = np.array([c.outcome.quote_valid is True for c in cells], dtype=np.float64)
    quoted = np.array([c.outcome.quote_valid is not None for c in cells], dtype=np.float64)
    ones = np.ones(n)
    out: Summary = {
        "n_cells": n,
        "accuracy": iv(bootstrap_interval(Sample(correct, ones), weights)),
        "wrong_value_rate": iv(bootstrap_interval(Sample(answered - correct, answered), weights)),
        "missing_rate": iv(bootstrap_interval(Sample(1 - answered, ones), weights)),
        "citation_validity": iv(bootstrap_interval(Sample(valid, quoted), weights)),
    }

    def grouped(key: Callable[[Any], str]) -> Summary:
        groups = sorted({key(c) for c in cells})
        rows: Summary = {}
        for g in groups:
            scores = kpi_scores([c.outcome for c in cells if key(c) == g])
            rows[g] = {
                "n": sum(1 for c in cells if key(c) == g),
                "accuracy": scores.accuracy,
                "wrong_value_rate": scores.wrong_value_rate,
                "missing_rate": scores.missing_rate,
            }
        return rows

    out["by_kpi"] = grouped(lambda c: c.kpi_id)
    out["by_period"] = grouped(lambda c: c.period)
    out["by_kind"] = grouped(lambda c: c.kind)
    out["per_seed"] = {r.label: kpi_scores([c.outcome for c in r.kpi]).accuracy for r in results}
    return out


def _screening(results: Sequence[SeedResult], pool: Pooler) -> Summary:
    pairs = [p for r in results for p in r.screening]
    scores = screening_scores(pairs)
    n = len(pairs)
    agree = np.array([t == p for t, p in pairs], dtype=np.float64)
    met = np.array([p == "met" for _, p in pairs], dtype=np.float64)
    wrong_met = np.array([p == "met" and t != "met" for t, p in pairs], dtype=np.float64)
    weights = pool.weights(n, 16)
    return {
        "n_cells": n,
        "agreement": iv(bootstrap_interval(Sample(agree, np.ones(n)), weights)),
        "false_met_rate": iv(bootstrap_interval(Sample(wrong_met, met), weights)),
        "point": {
            "unknown_rate": scores.unknown_rate,
            "accuracy_known": scores.accuracy_known,
        },
    }


# ---------------------------------------------------------------------------- performance


def _performance(results: Sequence[SeedResult], provider: str) -> Summary:
    def stats(values: Sequence[float]) -> dict[str, float | int | None]:
        return {"n": len(values), "p50": percentile(values, 50), "p95": percentile(values, 95)}

    stages: dict[str, list[float]] = {}
    for r in results:
        for stage, values in r.timing.stage_ms.items():
            stages.setdefault(stage, []).extend(values)
    costs = [c for r in results for c in r.timing.cost_usd]
    cost = 0.0 if provider == "mock" else mean_cost(costs)
    return {
        "search_ms": {
            s: stats([v for r in results for v in r.timing.search_ms.get(s, [])]) for s in SYSTEMS
        },
        "stage_ms": {k: stats(v) for k, v in sorted(stages.items())},
        "ask_wall_ms": stats([v for r in results for v in r.timing.ask_wall_ms]),
        "cost_per_query_usd": cost,
        "cost_basis": "zero by definition (mock provider)"
        if provider == "mock"
        else "token usage times the price table"
        if cost is not None
        else "not priced",
        "input_tokens_per_query": _mean([t for r in results for t in r.timing.input_tokens]),
        "output_tokens_per_query": _mean([t for r in results for t in r.timing.output_tokens]),
    }


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


# ---------------------------------------------------------------------------- entry point


def summarise(
    results: Sequence[SeedResult],
    *,
    provider: str,
    sweep_notes: dict[str, str],
    hand_labels: dict[str, Any] | None,
    n_resamples: int = DEFAULT_RESAMPLES,
) -> Summary:
    pool = Pooler(n_resamples, BOOTSTRAP_SEED)
    summary: Summary = {
        "seeds": [r.label for r in results],
        "counts": {r.label: r.counts for r in results},
        "generation_params": {r.label: r.params for r in results},
        "missing_truth_files": {
            r.label: r.missing_truth_files for r in results if r.missing_truth_files
        },
        "retrieval": _retrieval(results, pool, sweep_notes),
        "citation": _citation(results, pool),
        "verifier": _verifier(results, pool),
        "abstention": _abstention(results, pool),
        "contradiction": _contradiction(results, pool),
        "kpi": _kpi(results, pool),
        "screening": _screening(results, pool),
        "judge": _judge(results, pool, hand_labels),
        "performance": _performance(results, provider),
    }
    return sanitize(summary)  # type: ignore[no-any-return]
