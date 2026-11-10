"""Write `RESULTS.md` from a summary. Every number is read from the summary, none is typed here.

The block between the RUN-METADATA markers (date, commit, machine) and the block between the
TIMING markers (wall clock latencies) are the only parts that differ between two runs of the
deterministic offline configuration.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ainma.contracts import VALUE_CONTRACT
from ainma.evaluation.harness import RETRIEVAL_METRICS, SYSTEMS

LIMITATIONS: tuple[str, ...] = (
    "Data is synthetic and templated: absolute scores are optimistic and say little about real "
    "documents; only differences between systems under identical conditions are informative.",
    "The same author wrote the generator and the system, so design assumptions may leak into both.",
    "The offline dense retriever is LSA, not a neural model; neural results are reported "
    "separately when produced.",
    "Tier weights are hand-set priors, ablated, not learned.",
    "The constructed judge labels are validated on a small hand-labelled sample only.",
    "No production traffic, no clinician-grade blind review equivalent, no user study.",
    "Bootstrap intervals assume exchangeable queries; the cluster bootstrap is a sensitivity "
    "check, not a proof.",
)
LIMITATIONS_PARAGRAPH = "Limitations. " + " ".join(
    f"({i}) {text}" for i, text in enumerate(LIMITATIONS, start=1)
)
MOCK_LABEL = "OFFLINE MOCK BASELINE, not an LLM result"

METADATA_BEGIN = "<!-- RUN-METADATA-BEGIN: differs between runs -->"
METADATA_END = "<!-- RUN-METADATA-END -->"
TIMING_BEGIN = "<!-- TIMING-BEGIN: wall clock, differs between runs -->"
TIMING_END = "<!-- TIMING-END -->"

SYSTEM_NAMES = {
    "A1": "BM25",
    "A2": "Dense (offline LSA unless stated)",
    "A3": "Hybrid, RRF fusion (k = 60)",
    "A4": "A3 plus reranker",
    "A5": "A4 plus source ranker (tier, recency, status, corroboration)",
}
METRIC_LABELS = {
    "ndcg@10": "nDCG@10",
    "recall@5": "Recall@5",
    "recall@10": "Recall@10",
    "recall@30": "Recall@30",
    "mrr": "MRR",
}


@dataclass(frozen=True)
class RunMeta:
    provider: str
    model: str
    seeds: Sequence[str]
    config_hash: str
    modes: Mapping[str, str]
    dataset: str
    smoke: bool
    n_resamples: int
    date: str
    commit: str
    machine: str
    regression: Mapping[str, Any] = field(default_factory=dict)
    backends: Mapping[str, str] = field(default_factory=dict)
    split: str = "test"
    abstain_basis: str = "relevance"

    @property
    def stub_components(self) -> list[str]:
        return sorted(name for name, mode in self.modes.items() if mode == "stub")


# ---------------------------------------------------------------------------- formatting


def num(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def interval(d: Mapping[str, Any] | None, digits: int = 3) -> str:
    if not d or d.get("estimate") is None:
        return "n/a"
    if d.get("lo") is None or d.get("hi") is None:
        return num(d["estimate"], digits)
    return f"{num(d['estimate'], digits)} [{num(d['lo'], digits)}, {num(d['hi'], digits)}]"


def mean_sd(d: Mapping[str, Any] | None, digits: int = 3) -> str:
    if not d or d.get("mean") is None:
        return "n/a"
    if d.get("sd") is None:
        return num(d["mean"], digits)
    return f"{num(d['mean'], digits)} +/- {num(d['sd'], digits)}"


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def basis(meta: RunMeta, modes: Sequence[str]) -> str:
    label = (
        MOCK_LABEL if meta.provider == "mock" else f"provider {meta.provider}, model {meta.model}"
    )
    parts = ", ".join(f"{m}={meta.modes.get(m, 'n/a')}" for m in modes)
    return f"_Basis: {label}. Components: {parts}._"


def section(title: str, body: Sequence[str]) -> str:
    return "\n\n".join([f"## {title}", *body, f"> {LIMITATIONS_PARAGRAPH}"])


# ---------------------------------------------------------------------------- sections


def _retrieval(meta: RunMeta, s: Mapping[str, Any]) -> str:
    r = s["retrieval"]
    metric_cols = [METRIC_LABELS[m] for m in RETRIEVAL_METRICS]
    systems_rows = [
        [f"{sid} {SYSTEM_NAMES[sid]}", *[interval(r["systems"][sid][m]) for m in RETRIEVAL_METRICS]]
        for sid in SYSTEMS
    ]
    across_rows = [
        [sid, *[mean_sd(r["across_seeds"][sid][m]) for m in RETRIEVAL_METRICS]] for sid in SYSTEMS
    ]
    per_seed_rows = [
        [label, str(row["n"]), *[num(row[sid]["ndcg@10"]) for sid in SYSTEMS]]
        for label, row in r["per_seed"].items()
    ]
    body = [
        basis(meta, ["search"]),
        f"Test split of the answerable queries, {r['n_queries']} queries pooled over the seeds, "
        "access filter on, same candidate set for every system. Intervals are 95 percent "
        f"percentile intervals of a paired bootstrap over queries ({meta.n_resamples} resamples).",
        table(["System", *metric_cols], systems_rows),
        "Mean and standard deviation across seeds:",
        table(["System", *metric_cols], across_rows),
        "nDCG@10 per seed:",
        table(["Seed", "Queries", *SYSTEMS], per_seed_rows),
        "Pairwise differences are later minus earlier system, on the same resamples for both. "
        "`share>0` is the share of resamples with a positive difference; `p (Holm)` is a "
        "bootstrap two sided p value adjusted over the ten pairs of the metric; the last column "
        "is the cluster bootstrap by source document (sensitivity check). The plain intervals "
        "are not corrected for multiplicity.",
        "Interpretation guard: A5 can lower pure relevance metrics by design, because it prefers "
        "higher tier and more recent sources. A5 is judged by the citation and contradiction "
        "metrics below, not by nDCG alone.",
    ]
    for metric in ("ndcg@10", "recall@10", "mrr"):
        rows = [
            [
                row["pair"],
                interval(row["diff"]),
                num(row["share_positive"]),
                num(row["p_holm"], 4),
                interval(row["cluster_diff"]),
            ]
            for row in r["pairwise"][metric]
        ]
        body += [
            f"Pairwise differences in {METRIC_LABELS[metric]}:",
            table(["Pair", "Difference [95% CI]", "share>0", "p (Holm)", "Cluster 95% CI"], rows),
        ]
    body.append(_sweeps(r["sweeps"]))
    return section("1. Retrieval and ablation of the ranking components", body)


def _sweeps(sweeps: Mapping[str, Any]) -> str:
    if not sweeps:
        return "Sensitivity sweeps (tier prior, RRF weights, recency half-life): not run."
    parts = ["Sensitivity sweeps of A5 against its default configuration (paired, same queries):"]
    for name, sweep in sweeps.items():
        if sweep["status"] != "run":
            parts.append(f"- {name}: not run ({sweep['note']}).")
            continue
        rows = [
            [
                label,
                *[
                    cell
                    for m in ("ndcg@10", "recall@10", "mrr")
                    for cell in (
                        interval(variant[m]["value"]),
                        interval(variant[m]["diff_vs_default"]),
                    )
                ],
            ]
            for label, variant in sweep["variants"].items()
        ]
        parts.append(
            f"{name}:\n\n"
            + table(
                [
                    "Variant",
                    "nDCG@10",
                    "diff vs default",
                    "Recall@10",
                    "diff vs default",
                    "MRR",
                    "diff vs default",
                ],
                rows,
            )
        )
    return "\n\n".join(parts)


def _citation(meta: RunMeta, s: Mapping[str, Any]) -> str:
    c = s["citation"]
    names = {
        "citation_precision": "Citation precision",
        "citation_recall": "Citation recall",
        "unsupported_claim_rate": "Unsupported-claim rate",
    }
    rows = [
        [
            names[key],
            interval(c["metrics"][key]["verifier_on"]),
            interval(c["metrics"][key]["verifier_off"]),
            interval(c["metrics"][key]["difference"]),
            num(c["metrics"][key]["share_positive"]),
        ]
        for key in names
    ]
    seed_rows = [
        [
            label,
            *[num(row[setting][key]) for key in names for setting in ("on", "off")],
        ]
        for label, row in c["per_seed"].items()
    ]
    across_rows = [
        [names[key], mean_sd(c["across_seeds"]["on"][key]), mean_sd(c["across_seeds"]["off"][key])]
        for key in names
    ]
    body = [
        basis(meta, ["ask", "checks"]),
        f"Pipeline A5 on the test split of the answerable queries ({c['n_queries']} queries "
        "pooled), with and without the verifier. A claim matches a gold fact when its value and "
        "the metric and period keywords appear in it; it is correctly cited when one of its "
        "citations is in the support set of the fact. The unsupported-claim rate uses a check "
        "that is independent of the pipeline (verbatim quote and numbers of the claim in the "
        "quotes).",
        table(
            [
                "Metric",
                "Verifier on [95% CI]",
                "Verifier off [95% CI]",
                "Difference [95% CI]",
                "share>0",
            ],
            rows,
        ),
        f"Sourced claims kept with the verifier: {c['claims_with_verifier']}; without: "
        f"{c['claims_without_verifier']}; dropped by the verifier: {c['dropped_claims']}.",
        "Mean and standard deviation across seeds:",
        table(["Metric", "Verifier on", "Verifier off"], across_rows),
        "Per seed:",
        table(
            [
                "Seed",
                "Precision on",
                "Precision off",
                "Recall on",
                "Recall off",
                "Unsupported on",
                "Unsupported off",
            ],
            seed_rows,
        ),
    ]
    return section("2. Citation fidelity and verifier ablation", body)


def _verifier(meta: RunMeta, s: Mapping[str, Any]) -> str:
    v = s["verifier"]
    names = {
        "recall_unsupported": "Recall of unsupported claims",
        "recall_partial": "Recall of partial claims",
        "recall_not_supported": "Recall of not fully supported claims",
        "precision": "Precision (flagged claims that are truly not fully supported)",
        "false_flag_rate": "False flag rate (supported claims flagged)",
    }
    rows = [[names[k], interval(v["metrics"][k])] for k in names]
    perturbation_rows = [[name, pct(value)] for name, value in v["recall_by_perturbation"].items()]
    body = [
        basis(meta, ["judge", "checks"]),
        f"Adversarial claims of the test split, {v['n_claims']} claims pooled. The verifier flags "
        "a claim when the judge label is not `supported` or the verbatim or numeric check fails. "
        "Positive class: partial or unsupported.",
        table(["Metric", "Value [95% CI]"], rows),
        "Recall of not fully supported claims by perturbation:",
        table(["Perturbation", "Recall"], perturbation_rows),
    ]
    return section("3. Verifier quality on adversarial claims", body)


def _abstention(meta: RunMeta, s: Mapping[str, Any]) -> str:
    a = s["abstention"]
    seed_rows = [
        [
            label,
            num(row["tau"], 4),
            num(row["dev_tau"], 4),
            f"{pct(row['dev_false_abstention'])} (target {pct(row['target_false_abstention'])}, "
            f"n={row['n_dev_answerable']})",
            pct(row["correct_abstention"]),
            pct(row["false_abstention"]),
            pct(row["precision"]),
            pct(row["e2e_correct_abstention"]),
            pct(row["e2e_false_abstention"]),
        ]
        for label, row in a["per_seed"].items()
    ]
    pooled_rows = [
        [
            "Correct abstention rate (unanswerable)",
            interval(a["score_based"]["correct_abstention"]),
            interval(a["end_to_end"]["correct_abstention"]),
        ],
        [
            "False abstention rate (answerable)",
            interval(a["score_based"]["false_abstention"]),
            interval(a["end_to_end"]["false_abstention"]),
        ],
    ]
    across_rows = [
        [key.replace("_", " "), mean_sd(a["across_seeds"][key])]
        for key in ("correct_abstention", "false_abstention", "precision")
    ]
    curve_rows = [
        [
            "above every score" if p["tau"] is None else num(p["tau"], 4),
            pct(p["correct_abstention"]),
            pct(p["false_abstention"]),
            pct(p["precision"]),
        ]
        for p in a["curve"]
    ]
    body = [
        basis(meta, ["search", "ask"]),
        f"One `tau` is frozen for every seed (`DEFAULT_TAU`, the value the API and the demo use). "
        "It was chosen once on the pooled dev queries of the five seeds: with `n` dev answerable "
        "queries and `m = floor(target * n)`, it is the (m+1)th smallest best passage score, so "
        "at most `m` dev queries score below it (the target is a false abstention rate of 10 "
        "percent). It is applied unchanged to the test split. The score compared with `tau` is the "
        f"`{meta.abstain_basis}` component of the best passage of system A5 (the relevance of the "
        "retrieval stage, not the trust weighted final score). `Score rule` abstains when the "
        "best score is below `tau`; `end to end` is the abstained flag of the full pipeline at "
        "the same `tau`. The per seed dev calibration is kept as an extra column: the distance "
        "between it and the applied value shows how much the seeds disagree.",
        table(
            [
                "Seed",
                "tau applied",
                "Dev tau of the seed",
                "Dev false abstention at tau applied",
                "Correct abstention",
                "False abstention",
                "Precision",
                "End to end correct",
                "End to end false",
            ],
            seed_rows,
        ),
        "Pooled over seeds, test split [95% CI]:",
        table(["Metric", "Score rule", "End to end"], pooled_rows),
        "Mean and standard deviation across seeds (score rule):",
        table(["Metric", "Mean +/- sd"], across_rows),
        "Hard unanswerable queries (they share vocabulary with the corpus) against easy ones, "
        f"score rule: hard {pct(a['hard_unanswerable']['correct_abstention'])} "
        f"(n={a['hard_unanswerable']['n']}), "
        f"easy {pct(a['easy_unanswerable']['correct_abstention'])} "
        f"(n={a['easy_unanswerable']['n']}).",
        "Threshold curve on the pooled test scores (abstain below tau):",
        table(["tau", "Abstention recall", "False abstention", "Precision"], curve_rows),
    ]
    return section("4. Abstention", body)


def _contradiction(meta: RunMeta, s: Mapping[str, Any]) -> str:
    c = s["contradiction"]
    rows = [
        [f"Detection recall (planted pairs, n={c['n_planted']})", interval(c["recall"])],
        [
            f"False positive rate (consistent controls, n={c['n_controls']})",
            interval(c["false_positive_rate"]),
        ],
        ["Precision", interval(c["precision"])],
        ["F1", interval(c["f1"])],
    ]
    sw = c["superseded_withdrawn"]
    seed_rows = [
        [label, pct(row["recall"]), pct(row["false_positive_rate"]), num(row["f1"])]
        for label, row in c["per_seed"].items()
    ]
    body = [
        basis(meta, ["ask"]),
        "A planted pair is detected when the answer to its question contains a contradiction that "
        "cites at least two of the documents of the pair. A control is a false positive when the "
        "same holds for a consistent control.",
        table(["Metric", "Value [95% CI]"], rows),
        f"Completeness: both sides cited in {pct(c['completeness']['both_sides_cited'])} of "
        f"{c['completeness']['n_detected']} detected pairs. Agreement of `stronger_side` with the "
        f"truth (informative only, the system is not asked to decide): "
        f"{pct(c['stronger_side_agreement']['share'])} of {c['stronger_side_agreement']['n']}.",
        f"Superseded and withdrawn cases (n={sw['n']}), scored separately, the expected behaviour "
        f"is a flag and not a contradiction: flagged {sw['flagged']}, reported as contradiction "
        f"{sw['contradicted_instead']}, cited without the flag {sw['unflagged']}, not surfaced "
        f"{sw['not_surfaced']}.",
        f"Stale-only cases (n={c['stale']['n']}) flagged as stale or missing: "
        f"{pct(c['stale']['flagged'])}.",
        "Per seed:",
        table(["Seed", "Recall", "False positive rate", "F1"], seed_rows),
    ]
    return section("5. Contradictions and flags", body)


def _extraction(meta: RunMeta, s: Mapping[str, Any]) -> str:
    k = s["kpi"]
    sc = s["screening"]
    rows = [
        [f"KPI accuracy within 0.5% (n={k['n_cells']} truth cells)", interval(k["accuracy"])],
        ["Wrong-value rate (the dangerous error)", interval(k["wrong_value_rate"])],
        ["Missing rate (the safe error)", interval(k["missing_rate"])],
        ["Citation validity of sourced values", interval(k["citation_validity"])],
    ]

    def group_rows(groups: Mapping[str, Any]) -> list[list[str]]:
        return [
            [
                name,
                str(g["n"]),
                pct(g["accuracy"]),
                pct(g["wrong_value_rate"]),
                pct(g["missing_rate"]),
            ]
            for name, g in groups.items()
        ]

    headers = ["Group", "Cells", "Accuracy", "Wrong value", "Missing"]
    screening_rows = [
        [f"Agreement with buyer truth (n={sc['n_cells']} cells)", interval(sc["agreement"])],
        ["Predicted met although not met", interval(sc["false_met_rate"])],
        ["Unknown rate", pct(sc["point"]["unknown_rate"])],
        ["Accuracy where a status was given", pct(sc["point"]["accuracy_known"])],
    ]
    body = [
        basis(meta, ["kpi", "screening"]),
        "KPI values are compared with the truth table the financial model was generated from, "
        "relative tolerance 0.5 percent; a missing value is not correct. Computed KPIs are "
        "scored from extracted inputs (end to end).",
        table(["Metric", "Value [95% CI]"], rows),
        "By kind:",
        table(headers, group_rows(k["by_kind"])),
        "By period:",
        table(headers, group_rows(k["by_period"])),
        "By KPI:",
        table(headers, group_rows(k["by_kpi"])),
        "Buyer screening criteria against the buyer truth table (a criterion the system did not "
        "return counts as unknown):",
        table(["Metric", "Value"], screening_rows),
    ]
    return section("6. Extraction and screening", body)


def _judge(meta: RunMeta, s: Mapping[str, Any]) -> str:
    j = s["judge"]
    labels = j["labels"]
    confusion_rows = [
        [f"constructed {label}", *[str(v) for v in row]]
        for label, row in zip(labels, j.get("confusion", []), strict=False)
    ]
    seed_rows = [[label, num(value)] for label, value in j["per_seed"].items()]
    hand = j["hand_labels"]
    if hand.get("status") == "scored":
        hc, hj = "human_constructed", "human_judge"
        hand_text = (
            f"Hand labels (n={hand['n_labelled']}): kappa human vs constructed "
            f"{num(hand['kappa_' + hc])} (weighted {num(hand['weighted_kappa_' + hc])}), "
            f"human vs judge {num(hand['kappa_' + hj])} "
            f"(weighted {num(hand['weighted_kappa_' + hj])}), "
            f"constructed vs judge on the same items {num(hand['kappa_constructed_judge'])}."
        )
    else:
        hand_text = f"Hand labels: {hand.get('status', 'not labelled yet')}."
    body = [
        basis(meta, ["judge"]),
        f"Judge labels against the constructed labels of the adversarial test split, "
        f"{j['n_claims']} claims pooled.",
        table(
            ["Statistic", "Value [95% CI]"],
            [
                ["Cohen's kappa", interval(j.get("kappa"))],
                ["Linearly weighted kappa", interval(j.get("weighted_kappa"))],
            ],
        ),
        "Confusion matrix (rows constructed, columns judge: " + ", ".join(labels) + "):",
        table(["", *labels], confusion_rows),
        "Kappa per seed:",
        table(["Seed", "Kappa"], seed_rows),
        hand_text,
        "Self-preference control: with the mock provider the same deterministic routine writes "
        "and judges; this is stated, not controlled. For a live run, name the writer and the "
        "judge model separately.",
    ]
    return section("7. Judge calibration", body)


def _performance(meta: RunMeta, s: Mapping[str, Any]) -> str:
    p = s["performance"]

    def row(name: str, d: Mapping[str, Any]) -> list[str]:
        return [name, str(d["n"]), num(d["p50"], 2), num(d["p95"], 2)]

    stage_rows = [row(f"stage: {k}", v) for k, v in p["stage_ms"].items()]
    rows = [
        *[row(f"search {sid}", p["search_ms"][sid]) for sid in SYSTEMS],
        *stage_rows,
        row("ask, total wall clock", p["ask_wall_ms"]),
    ]
    body = [
        basis(meta, ["search", "ask"]),
        f"Cost per query: {num(p['cost_per_query_usd'], 6)} USD. Basis: {p['cost_basis']}. "
        f"Mean tokens per query: input {num(p['input_tokens_per_query'], 1)}, output "
        f"{num(p['output_tokens_per_query'], 1)}. For the deterministic offline configuration the "
        "run to run variance of every metric is zero by construction; the across-seed variance "
        "is reported with each table.",
        "Latency in milliseconds, test queries, warm in memory store, machine as in the header "
        "(the timing block differs between runs):",
        TIMING_BEGIN,
        table(
            [
                "Measure",
                "n",
                "p50 (ms, wall clock, differs on every run)",
                "p95 (ms, wall clock, differs on every run)",
            ],
            rows,
        ),
        TIMING_END,
    ]
    return section("8. Latency and cost", body)


def _regression(meta: RunMeta) -> str:
    r = meta.regression
    n_cases = int(r.get("n_cases", 0))
    lines = [f"Regression cases replayed: {n_cases} cases, {int(r.get('n_passed', 0))} passed."]
    failures = r.get("failures", [])
    if n_cases == 0:
        lines = ["Regression cases replayed: 0 cases (the `eval/regression/` directory is empty)."]
    rows = [[f["id"], f["reason"]] for f in failures]
    body = [basis(meta, ["ask"]), *lines]
    if rows:
        body.append(table(["Case", "Reason"], rows))
    else:
        body.append(
            table(
                ["Cases", "Passed", "Failed"],
                [[str(n_cases), str(r.get("n_passed", 0)), str(len(failures))]],
            )
        )
    return section("9. Regression replay", body)


def _abstention_precision(s: Mapping[str, Any]) -> str:
    """Share of the abstentions of the full pipeline that were on unanswerable questions."""
    return num(s["abstention"].get("end_to_end_precision"))


def _principle(meta: RunMeta, s: Mapping[str, Any]) -> str:
    c, a, k = s["citation"]["metrics"], s["abstention"]["end_to_end"], s["contradiction"]
    rows = [
        ["Citation precision (verifier on)", interval(c["citation_precision"]["verifier_on"])],
        ["Citation recall (verifier on)", interval(c["citation_recall"]["verifier_on"])],
        ["Correct abstention, end to end", interval(a["correct_abstention"])],
        ["False abstention, end to end", interval(a["false_abstention"])],
        [
            "Abstention precision (abstentions on unanswerable questions / all abstentions)",
            _abstention_precision(s),
        ],
        ["Contradiction detection recall", interval(k["recall"])],
        [
            "Clicks to verify a claim",
            "1 by design; asserted by the end to end test of the app, not measured here",
        ],
    ]
    body = [
        basis(meta, ["search", "ask"]),
        f"Value contract: {VALUE_CONTRACT}",
        table(["Principle metric", "Value [95% CI]"], rows),
    ]
    return section("0. Principle metrics", body)


# ---------------------------------------------------------------------------- document


def _difficulty_lines(s: Mapping[str, Any]) -> list[str]:
    """The difficulty knobs of each seed: a reported parameter, not a hidden one."""
    params = s.get("generation_params") or {}
    return [
        f"- Difficulty, seed {label}: paraphrase_rate={p.get('paraphrase_rate', 'n/a')}, "
        f"hard_negative_rate={p.get('hard_negative_rate', 'n/a')}"
        for label, p in params.items()
    ]


def _tau_lines(s: Mapping[str, Any], meta: RunMeta) -> list[str]:
    a = s.get("abstention", {})
    frozen, pooled = a.get("frozen_tau"), a.get("pooled_dev_tau")
    if frozen is None and pooled is None:
        return []
    lines = [f"- Abstention score: `{meta.abstain_basis}` of the best passage"]
    if frozen is not None:
        lines.append(
            f"- Frozen tau (`DEFAULT_TAU`, used by the API and the test split): {frozen:.4f}"
        )
    if pooled is not None:
        drift = (
            "" if frozen is None else f" (difference to the frozen value {pooled - frozen:+.4f})"
        )
        lines.append(f"- Pooled dev tau recomputed in this run: {pooled:.4f}{drift}")
    return lines


def render_report(summary: Mapping[str, Any], meta: RunMeta) -> str:
    banners: list[str] = []
    if meta.provider == "mock":
        banners.append(f"**{MOCK_LABEL}.**")
    if meta.stub_components:
        banners.append(
            "**STUB COMPONENTS: "
            + ", ".join(meta.stub_components)
            + ". Numbers that depend on them come from deterministic stubs, not from the system.**"
        )
    if meta.split != "test":
        banners.append(
            f"**SPLIT `{meta.split}`: development measurement. Thresholds and design choices are "
            "made on the dev split, so this file must not be quoted as a result; the report is "
            "the default run on the test split.**"
        )
    if meta.smoke:
        banners.append(
            "**SMOKE RUN on a tiny fixture corpus. It proves that the flow runs, it measures "
            "nothing, and no number of this file may be quoted.**"
        )
    header = "\n\n".join(
        [
            "# Evaluation results",
            *banners,
            "\n".join(
                [
                    METADATA_BEGIN,
                    f"- Date: {meta.date}",
                    f"- Git commit: {meta.commit}",
                    f"- Machine: {meta.machine}",
                    METADATA_END,
                ]
            ),
            "\n".join(
                [
                    f"- Provider: {meta.provider}, model: {meta.model}",
                    f"- Seeds: {', '.join(meta.seeds)}",
                    f"- Split: {meta.split}",
                    f"- Configuration hash: {meta.config_hash}",
                    "- Components: " + ", ".join(f"{k}={v}" for k, v in sorted(meta.modes.items())),
                    "- Backends: "
                    + ", ".join(f"{k}={v}" for k, v in sorted(meta.backends.items())),
                    f"- Dataset: {meta.dataset}",
                    *_difficulty_lines(summary),
                    *_tau_lines(summary, meta),
                    f"- Bootstrap: {meta.n_resamples} resamples, 95 percent percentile intervals",
                ]
            ),
        ]
    )
    sections = [
        _principle(meta, summary),
        _retrieval(meta, summary),
        _citation(meta, summary),
        _verifier(meta, summary),
        _abstention(meta, summary),
        _contradiction(meta, summary),
        _extraction(meta, summary),
        _judge(meta, summary),
        _performance(meta, summary),
        _regression(meta),
    ]
    return header + "\n\n" + "\n\n".join(sections) + "\n"


def strip_run_dependent(markdown: str) -> str:
    """The report without the metadata and timing blocks (what must be identical between runs)."""
    for begin, end in ((METADATA_BEGIN, METADATA_END), (TIMING_BEGIN, TIMING_END)):
        markdown = re.sub(f"{re.escape(begin)}.*?{re.escape(end)}", "", markdown, flags=re.S)
    return markdown
