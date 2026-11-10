# Evaluation results

**OFFLINE MOCK BASELINE, not an LLM result.**

<!-- RUN-METADATA-BEGIN: differs between runs -->
- Date: 2026-11-10
- Git commit: da5d470
- Machine: Darwin 27.0.0 arm64, Python 3.12.2, 8 CPUs
<!-- RUN-METADATA-END -->

- Provider: mock, model: mock-extractive-v1
- Seeds: 1234, 1, 2, 3, 4
- Split: test
- Configuration hash: c628b9eda400fe54
- Components: ask=real, checks=real, judge=real, kpi=real, screening=real, search=real
- Backends: dense=lsa, reranker=features
- Dataset: generated corpora under data/synthetic/<seed>/
- Bootstrap: 2000 resamples, 95 percent percentile intervals

## 0. Principle metrics

_Basis: OFFLINE MOCK BASELINE, not an LLM result. Components: search=real, ask=real._

Value contract: I summarise the evidence clearly and show you the sources, so that you can examine them and make informed decisions.

| Principle metric | Value [95% CI] |
|---|---|
| Citation precision (verifier on) | 0.909 [0.892, 0.927] |
| Citation recall (verifier on) | 0.931 [0.917, 0.945] |
| Correct abstention, end to end | 0.913 [0.867, 0.953] |
| Contradiction detection recall | 0.954 [0.920, 0.983] |
| Clicks to verify a claim | 1 by design; asserted by the end to end test of the app, not measured here |

> Limitations. (1) Data is synthetic and templated: absolute scores are optimistic and say little about real documents; only differences between systems under identical conditions are informative. (2) The same author wrote the generator and the system, so design assumptions may leak into both. (3) The offline dense retriever is LSA, not a neural model; neural results are reported separately when produced. (4) Tier weights are hand-set priors, ablated, not learned. (5) The constructed judge labels are validated on a small hand-labelled sample only. (6) No production traffic, no clinician-grade blind review equivalent, no user study. (7) Bootstrap intervals assume exchangeable queries; the cluster bootstrap is a sensitivity check, not a proof.

## 1. Retrieval and ablation of the ranking components

_Basis: OFFLINE MOCK BASELINE, not an LLM result. Components: search=real._

Test split of the answerable queries, 1188 queries pooled over the seeds, access filter on, same candidate set for every system. Intervals are 95 percent percentile intervals of a paired bootstrap over queries (2000 resamples).

| System | nDCG@10 | Recall@5 | Recall@10 | Recall@30 | MRR |
|---|---|---|---|---|---|
| A1 BM25 | 0.744 [0.727, 0.759] | 0.816 [0.797, 0.835] | 0.882 [0.866, 0.897] | 0.956 [0.947, 0.965] | 0.665 [0.644, 0.685] |
| A2 Dense (offline LSA unless stated) | 0.699 [0.681, 0.716] | 0.781 [0.760, 0.801] | 0.867 [0.851, 0.884] | 0.936 [0.924, 0.947] | 0.615 [0.594, 0.636] |
| A3 Hybrid, RRF fusion (k = 60) | 0.720 [0.703, 0.735] | 0.805 [0.785, 0.823] | 0.887 [0.871, 0.902] | 0.948 [0.937, 0.958] | 0.632 [0.611, 0.652] |
| A4 A3 plus reranker | 0.927 [0.921, 0.933] | 0.998 [0.997, 0.999] | 1.000 [0.999, 1.000] | 1.000 [0.999, 1.000] | 0.836 [0.822, 0.849] |
| A5 A4 plus source ranker (tier, recency, status, corroboration) | 0.960 [0.955, 0.965] | 0.999 [0.998, 1.000] | 1.000 [0.999, 1.000] | 1.000 [0.999, 1.000] | 0.919 [0.908, 0.930] |

Mean and standard deviation across seeds:

| System | nDCG@10 | Recall@5 | Recall@10 | Recall@30 | MRR |
|---|---|---|---|---|---|
| A1 | 0.744 +/- 0.011 | 0.816 +/- 0.018 | 0.882 +/- 0.010 | 0.956 +/- 0.011 | 0.665 +/- 0.012 |
| A2 | 0.699 +/- 0.019 | 0.781 +/- 0.017 | 0.868 +/- 0.014 | 0.936 +/- 0.011 | 0.615 +/- 0.022 |
| A3 | 0.720 +/- 0.014 | 0.805 +/- 0.020 | 0.887 +/- 0.009 | 0.948 +/- 0.014 | 0.632 +/- 0.018 |
| A4 | 0.927 +/- 0.005 | 0.998 +/- 0.001 | 1.000 +/- 0.001 | 1.000 +/- 0.001 | 0.836 +/- 0.012 |
| A5 | 0.960 +/- 0.003 | 0.999 +/- 0.002 | 1.000 +/- 0.001 | 1.000 +/- 0.001 | 0.919 +/- 0.004 |

nDCG@10 per seed:

| Seed | Queries | A1 | A2 | A3 | A4 | A5 |
|---|---|---|---|---|---|---|
| 1234 | 238 | 0.743 | 0.688 | 0.705 | 0.925 | 0.960 |
| 1 | 235 | 0.740 | 0.682 | 0.712 | 0.936 | 0.955 |
| 2 | 241 | 0.731 | 0.689 | 0.714 | 0.927 | 0.961 |
| 3 | 238 | 0.759 | 0.730 | 0.737 | 0.923 | 0.962 |
| 4 | 236 | 0.748 | 0.705 | 0.731 | 0.925 | 0.961 |

Pairwise differences are later minus earlier system, on the same resamples for both. `share>0` is the share of resamples with a positive difference; `p (Holm)` is a bootstrap two sided p value adjusted over the ten pairs of the metric; the last column is the cluster bootstrap by source document (sensitivity check). The plain intervals are not corrected for multiplicity.

Interpretation guard: A5 can lower pure relevance metrics by design, because it prefers higher tier and more recent sources. A5 is judged by the citation and contradiction metrics below, not by nDCG alone.

Pairwise differences in nDCG@10:

| Pair | Difference [95% CI] | share>0 | p (Holm) | Cluster 95% CI |
|---|---|---|---|---|
| A2 - A1 | -0.045 [-0.056, -0.034] | 0.000 | 0.0050 | -0.045 [-0.058, -0.031] |
| A3 - A1 | -0.024 [-0.030, -0.018] | 0.000 | 0.0050 | -0.024 [-0.031, -0.017] |
| A4 - A1 | 0.183 [0.167, 0.200] | 1.000 | 0.0050 | 0.183 [0.161, 0.204] |
| A5 - A1 | 0.216 [0.200, 0.233] | 1.000 | 0.0050 | 0.216 [0.196, 0.235] |
| A3 - A2 | 0.021 [0.014, 0.027] | 1.000 | 0.0050 | 0.021 [0.012, 0.029] |
| A4 - A2 | 0.228 [0.211, 0.247] | 1.000 | 0.0050 | 0.228 [0.198, 0.257] |
| A5 - A2 | 0.261 [0.243, 0.279] | 1.000 | 0.0050 | 0.261 [0.232, 0.286] |
| A4 - A3 | 0.208 [0.191, 0.224] | 1.000 | 0.0050 | 0.208 [0.182, 0.231] |
| A5 - A3 | 0.240 [0.224, 0.257] | 1.000 | 0.0050 | 0.240 [0.218, 0.261] |
| A5 - A4 | 0.033 [0.026, 0.039] | 1.000 | 0.0050 | 0.033 [0.025, 0.040] |

Pairwise differences in Recall@10:

| Pair | Difference [95% CI] | share>0 | p (Holm) | Cluster 95% CI |
|---|---|---|---|---|
| A2 - A1 | -0.015 [-0.025, -0.004] | 0.002 | 0.0120 | -0.015 [-0.027, -0.001] |
| A3 - A1 | 0.005 [-0.002, 0.011] | 0.924 | 0.3040 | 0.005 [-0.001, 0.012] |
| A4 - A1 | 0.117 [0.103, 0.134] | 1.000 | 0.0050 | 0.117 [0.099, 0.136] |
| A5 - A1 | 0.117 [0.103, 0.134] | 1.000 | 0.0050 | 0.117 [0.099, 0.136] |
| A3 - A2 | 0.020 [0.012, 0.028] | 1.000 | 0.0050 | 0.020 [0.010, 0.029] |
| A4 - A2 | 0.132 [0.115, 0.149] | 1.000 | 0.0050 | 0.132 [0.108, 0.154] |
| A5 - A2 | 0.132 [0.115, 0.149] | 1.000 | 0.0050 | 0.132 [0.108, 0.154] |
| A4 - A3 | 0.112 [0.098, 0.128] | 1.000 | 0.0050 | 0.112 [0.092, 0.132] |
| A5 - A3 | 0.112 [0.098, 0.128] | 1.000 | 0.0050 | 0.112 [0.092, 0.132] |
| A5 - A4 | 0.000 [0.000, 0.000] | 0.000 | 1.0000 | 0.000 [0.000, 0.000] |

Pairwise differences in MRR:

| Pair | Difference [95% CI] | share>0 | p (Holm) | Cluster 95% CI |
|---|---|---|---|---|
| A2 - A1 | -0.050 [-0.063, -0.037] | 0.000 | 0.0050 | -0.050 [-0.063, -0.035] |
| A3 - A1 | -0.033 [-0.042, -0.025] | 0.000 | 0.0050 | -0.033 [-0.041, -0.024] |
| A4 - A1 | 0.171 [0.153, 0.191] | 1.000 | 0.0050 | 0.171 [0.145, 0.195] |
| A5 - A1 | 0.254 [0.234, 0.274] | 1.000 | 0.0050 | 0.254 [0.231, 0.275] |
| A3 - A2 | 0.017 [0.008, 0.026] | 1.000 | 0.0050 | 0.017 [0.006, 0.027] |
| A4 - A2 | 0.221 [0.201, 0.243] | 1.000 | 0.0050 | 0.221 [0.188, 0.252] |
| A5 - A2 | 0.304 [0.282, 0.325] | 1.000 | 0.0050 | 0.304 [0.275, 0.330] |
| A4 - A3 | 0.204 [0.185, 0.223] | 1.000 | 0.0050 | 0.204 [0.178, 0.229] |
| A5 - A3 | 0.287 [0.266, 0.307] | 1.000 | 0.0050 | 0.287 [0.262, 0.308] |
| A5 - A4 | 0.083 [0.070, 0.095] | 1.000 | 0.0050 | 0.083 [0.066, 0.099] |

Sensitivity sweeps of A5 against its default configuration (paired, same queries):

tier prior uniform:

| Variant | nDCG@10 | diff vs default | Recall@10 | diff vs default | MRR | diff vs default |
|---|---|---|---|---|---|---|
| uniform | 0.944 [0.938, 0.950] | -0.015 [-0.019, -0.012] | 1.000 [0.999, 1.000] | 0.000 [0.000, 0.000] | 0.880 [0.867, 0.892] | -0.039 [-0.047, -0.031] |

RRF weights:

| Variant | nDCG@10 | diff vs default | Recall@10 | diff vs default | MRR | diff vs default |
|---|---|---|---|---|---|---|
| first x2 | 0.960 [0.955, 0.965] | 0.000 [-0.000, 0.001] | 1.000 [0.999, 1.000] | 0.000 [0.000, 0.000] | 0.919 [0.908, 0.930] | 0.000 [0.000, 0.001] |
| second x2 | 0.960 [0.955, 0.965] | 0.000 [-0.001, 0.001] | 1.000 [0.999, 1.000] | 0.000 [0.000, 0.000] | 0.919 [0.908, 0.929] | -0.000 [-0.002, 0.002] |

recency half-life:

| Variant | nDCG@10 | diff vs default | Recall@10 | diff vs default | MRR | diff vs default |
|---|---|---|---|---|---|---|
| x0.5 | 0.944 [0.937, 0.951] | -0.016 [-0.021, -0.011] | 0.999 [0.997, 1.000] | -0.001 [-0.003, 0.000] | 0.899 [0.886, 0.911] | -0.020 [-0.027, -0.014] |
| x2 | 0.963 [0.958, 0.968] | 0.004 [0.002, 0.006] | 1.000 [0.999, 1.000] | 0.000 [0.000, 0.000] | 0.924 [0.913, 0.934] | 0.005 [0.002, 0.008] |

> Limitations. (1) Data is synthetic and templated: absolute scores are optimistic and say little about real documents; only differences between systems under identical conditions are informative. (2) The same author wrote the generator and the system, so design assumptions may leak into both. (3) The offline dense retriever is LSA, not a neural model; neural results are reported separately when produced. (4) Tier weights are hand-set priors, ablated, not learned. (5) The constructed judge labels are validated on a small hand-labelled sample only. (6) No production traffic, no clinician-grade blind review equivalent, no user study. (7) Bootstrap intervals assume exchangeable queries; the cluster bootstrap is a sensitivity check, not a proof.

## 2. Citation fidelity and verifier ablation

_Basis: OFFLINE MOCK BASELINE, not an LLM result. Components: ask=real, checks=real._

Pipeline A5 on the test split of the answerable queries (1188 queries pooled), with and without the verifier. A claim matches a gold fact when its value and the metric and period keywords appear in it; it is correctly cited when one of its citations is in the support set of the fact. The unsupported-claim rate uses a check that is independent of the pipeline (verbatim quote and numbers of the claim in the quotes).

| Metric | Verifier on [95% CI] | Verifier off [95% CI] | Difference [95% CI] | share>0 |
|---|---|---|---|---|
| Citation precision | 0.909 [0.892, 0.927] | 0.909 [0.892, 0.927] | 0.000 [0.000, 0.000] | 0.000 |
| Citation recall | 0.931 [0.917, 0.945] | 0.931 [0.917, 0.945] | 0.000 [0.000, 0.000] | 0.000 |
| Unsupported-claim rate | 0.005 [0.001, 0.008] | 0.005 [0.001, 0.008] | 0.000 [0.000, 0.000] | 0.000 |

Sourced claims kept with the verifier: 1489; without: 1489; dropped by the verifier: 0.

Mean and standard deviation across seeds:

| Metric | Verifier on | Verifier off |
|---|---|---|
| Citation precision | 0.909 +/- 0.012 | 0.909 +/- 0.012 |
| Citation recall | 0.931 +/- 0.009 | 0.931 +/- 0.009 |
| Unsupported-claim rate | 0.005 +/- 0.003 | 0.005 +/- 0.003 |

Per seed:

| Seed | Precision on | Precision off | Recall on | Recall off | Unsupported on | Unsupported off |
|---|---|---|---|---|---|---|
| 1234 | 0.916 | 0.916 | 0.920 | 0.920 | 0.007 | 0.007 |
| 1 | 0.898 | 0.898 | 0.935 | 0.935 | 0.000 | 0.000 |
| 2 | 0.910 | 0.910 | 0.940 | 0.940 | 0.003 | 0.003 |
| 3 | 0.926 | 0.926 | 0.938 | 0.938 | 0.007 | 0.007 |
| 4 | 0.897 | 0.897 | 0.922 | 0.922 | 0.007 | 0.007 |

> Limitations. (1) Data is synthetic and templated: absolute scores are optimistic and say little about real documents; only differences between systems under identical conditions are informative. (2) The same author wrote the generator and the system, so design assumptions may leak into both. (3) The offline dense retriever is LSA, not a neural model; neural results are reported separately when produced. (4) Tier weights are hand-set priors, ablated, not learned. (5) The constructed judge labels are validated on a small hand-labelled sample only. (6) No production traffic, no clinician-grade blind review equivalent, no user study. (7) Bootstrap intervals assume exchangeable queries; the cluster bootstrap is a sensitivity check, not a proof.

## 3. Verifier quality on adversarial claims

_Basis: OFFLINE MOCK BASELINE, not an LLM result. Components: judge=real, checks=real._

Adversarial claims of the test split, 1400 claims pooled. The verifier flags a claim when the judge label is not `supported` or the verbatim or numeric check fails. Positive class: partial or unsupported.

| Metric | Value [95% CI] |
|---|---|
| Recall of unsupported claims | 0.918 [0.901, 0.935] |
| Recall of partial claims | 1.000 [1.000, 1.000] |
| Recall of not fully supported claims | 0.934 [0.920, 0.948] |
| Precision (flagged claims that are truly not fully supported) | 1.000 [1.000, 1.000] |
| False flag rate (supported claims flagged) | 0.000 [0.000, 0.000] |

Recall of not fully supported claims by perturbation:

| Perturbation | Recall |
|---|---|
| altered_entity | 68.3% |
| altered_number | 100.0% |
| altered_period | 98.7% |
| half_true | 100.0% |
| none | n/a |
| unrelated | 100.0% |

> Limitations. (1) Data is synthetic and templated: absolute scores are optimistic and say little about real documents; only differences between systems under identical conditions are informative. (2) The same author wrote the generator and the system, so design assumptions may leak into both. (3) The offline dense retriever is LSA, not a neural model; neural results are reported separately when produced. (4) Tier weights are hand-set priors, ablated, not learned. (5) The constructed judge labels are validated on a small hand-labelled sample only. (6) No production traffic, no clinician-grade blind review equivalent, no user study. (7) Bootstrap intervals assume exchangeable queries; the cluster bootstrap is a sensitivity check, not a proof.

## 4. Abstention

_Basis: OFFLINE MOCK BASELINE, not an LLM result. Components: search=real, ask=real._

`tau` is chosen on the dev queries only (largest threshold whose false abstention rate on dev stays at or below the target), frozen, and reported on the test split. The score is the best final passage score of system A5. `Score rule` abstains when the best score is below `tau`; `end to end` is the abstained flag of the full pipeline at the frozen `tau`.

| Seed | tau | Dev false abstention | Correct abstention | False abstention | Precision | End to end correct | End to end false |
|---|---|---|---|---|---|---|---|
| 1234 | 0.5968 | 8.2% (target 10.0%, n=98) | 90.0% | 10.9% | 50.9% | 90.0% | 8.8% |
| 1 | 0.5877 | 9.4% (target 10.0%, n=96) | 90.0% | 8.9% | 56.2% | 90.0% | 7.7% |
| 2 | 0.5827 | 9.1% (target 10.0%, n=99) | 93.3% | 6.6% | 63.6% | 93.3% | 6.6% |
| 3 | 0.5991 | 9.2% (target 10.0%, n=98) | 90.0% | 8.8% | 56.2% | 90.0% | 6.7% |
| 4 | 0.5952 | 9.2% (target 10.0%, n=98) | 90.0% | 10.2% | 52.9% | 93.3% | 9.3% |

Pooled over seeds, test split [95% CI]:

| Metric | Score rule | End to end |
|---|---|---|
| Correct abstention rate (unanswerable) | 0.907 [0.860, 0.947] | 0.913 [0.867, 0.953] |
| False abstention rate (answerable) | 0.091 [0.076, 0.109] | 0.078 [0.063, 0.094] |

Mean and standard deviation across seeds (score rule):

| Metric | Mean +/- sd |
|---|---|
| correct abstention | 0.907 +/- 0.015 |
| false abstention | 0.091 +/- 0.016 |
| precision | 0.560 +/- 0.048 |

Hard unanswerable queries (they share vocabulary with the corpus) against easy ones, score rule: hard 78.5% (n=65), easy 100.0% (n=85).

Threshold curve on the pooled test scores (abstain below tau):

| tau | Abstention recall | False abstention | Precision |
|---|---|---|---|
| 0.1952 | 0.0% | 0.0% | n/a |
| 0.5317 | 81.3% | 1.0% | 91.0% |
| 0.5827 | 90.7% | 7.2% | 61.3% |
| 0.6099 | 92.0% | 13.6% | 46.0% |
| 0.6514 | 100.0% | 15.7% | 44.5% |
| 0.6763 | 100.0% | 30.6% | 29.2% |
| 0.7270 | 100.0% | 35.2% | 26.4% |
| 0.7481 | 100.0% | 50.6% | 20.0% |
| 0.7800 | 100.0% | 61.4% | 17.1% |
| 0.8122 | 100.0% | 66.5% | 16.0% |
| 0.9789 | 100.0% | 76.9% | 14.1% |
| above every score | 100.0% | 100.0% | 11.2% |

> Limitations. (1) Data is synthetic and templated: absolute scores are optimistic and say little about real documents; only differences between systems under identical conditions are informative. (2) The same author wrote the generator and the system, so design assumptions may leak into both. (3) The offline dense retriever is LSA, not a neural model; neural results are reported separately when produced. (4) Tier weights are hand-set priors, ablated, not learned. (5) The constructed judge labels are validated on a small hand-labelled sample only. (6) No production traffic, no clinician-grade blind review equivalent, no user study. (7) Bootstrap intervals assume exchangeable queries; the cluster bootstrap is a sensitivity check, not a proof.

## 5. Contradictions and flags

_Basis: OFFLINE MOCK BASELINE, not an LLM result. Components: ask=real._

A planted pair is detected when the answer to its question contains a contradiction that cites at least two of the documents of the pair. A control is a false positive when the same holds for a consistent control.

| Metric | Value [95% CI] |
|---|---|
| Detection recall (planted pairs, n=174) | 0.954 [0.920, 0.983] |
| False positive rate (consistent controls, n=472) | 0.000 [0.000, 0.000] |
| Precision | 1.000 [1.000, 1.000] |
| F1 | 0.976 [0.959, 0.991] |

Completeness: both sides cited in 100.0% of 166 detected pairs. Agreement of `stronger_side` with the truth (informative only, the system is not asked to decide): 100.0% of 166.

Superseded and withdrawn cases (n=42), scored separately, the expected behaviour is a flag and not a contradiction: flagged 34, reported as contradiction 0, cited without the flag 4, not surfaced 4.

Stale-only cases (n=125) flagged as stale or missing: 89.6%.

Per seed:

| Seed | Recall | False positive rate | F1 |
|---|---|---|---|
| 1234 | 93.9% | 0.0% | 0.969 |
| 1 | 97.3% | 0.0% | 0.986 |
| 2 | 94.3% | 0.0% | 0.971 |
| 3 | 94.4% | 0.0% | 0.971 |
| 4 | 97.0% | 0.0% | 0.985 |

> Limitations. (1) Data is synthetic and templated: absolute scores are optimistic and say little about real documents; only differences between systems under identical conditions are informative. (2) The same author wrote the generator and the system, so design assumptions may leak into both. (3) The offline dense retriever is LSA, not a neural model; neural results are reported separately when produced. (4) Tier weights are hand-set priors, ablated, not learned. (5) The constructed judge labels are validated on a small hand-labelled sample only. (6) No production traffic, no clinician-grade blind review equivalent, no user study. (7) Bootstrap intervals assume exchangeable queries; the cluster bootstrap is a sensitivity check, not a proof.

## 6. Extraction and screening

_Basis: OFFLINE MOCK BASELINE, not an LLM result. Components: kpi=real, screening=real._

KPI values are compared with the truth table the financial model was generated from, relative tolerance 0.5 percent; a missing value is not correct. Computed KPIs are scored from extracted inputs (end to end).

| Metric | Value [95% CI] |
|---|---|
| KPI accuracy within 0.5% (n=500 truth cells) | 0.994 [0.986, 1.000] |
| Wrong-value rate (the dangerous error) | 0.006 [0.000, 0.014] |
| Missing rate (the safe error) | 0.000 [0.000, 0.000] |
| Citation validity of sourced values | 1.000 [1.000, 1.000] |

By kind:

| Group | Cells | Accuracy | Wrong value | Missing |
|---|---|---|---|---|
| compute | 200 | 99.0% | 1.0% | 0.0% |
| extract | 300 | 99.7% | 0.3% | 0.0% |

By period:

| Group | Cells | Accuracy | Wrong value | Missing |
|---|---|---|---|---|
| FY2020 | 100 | 100.0% | 0.0% | 0.0% |
| FY2021 | 100 | 100.0% | 0.0% | 0.0% |
| FY2022 | 100 | 100.0% | 0.0% | 0.0% |
| FY2023 | 100 | 100.0% | 0.0% | 0.0% |
| FY2024 | 100 | 97.0% | 3.0% | 0.0% |

By KPI:

| Group | Cells | Accuracy | Wrong value | Missing |
|---|---|---|---|---|
| capex | 25 | 100.0% | 0.0% | 0.0% |
| cash | 25 | 96.0% | 4.0% | 0.0% |
| cogs | 25 | 100.0% | 0.0% | 0.0% |
| ebit | 25 | 100.0% | 0.0% | 0.0% |
| ebitda | 25 | 100.0% | 0.0% | 0.0% |
| ebitda_margin | 25 | 100.0% | 0.0% | 0.0% |
| free_cash_flow | 25 | 100.0% | 0.0% | 0.0% |
| gross_margin | 25 | 100.0% | 0.0% | 0.0% |
| gross_profit | 25 | 100.0% | 0.0% | 0.0% |
| interest_coverage | 25 | 100.0% | 0.0% | 0.0% |
| interest_expense | 25 | 100.0% | 0.0% | 0.0% |
| leverage | 25 | 96.0% | 4.0% | 0.0% |
| net_debt | 25 | 96.0% | 4.0% | 0.0% |
| net_income | 25 | 100.0% | 0.0% | 0.0% |
| net_margin | 25 | 100.0% | 0.0% | 0.0% |
| operating_cash_flow | 25 | 100.0% | 0.0% | 0.0% |
| revenue | 25 | 100.0% | 0.0% | 0.0% |
| total_assets | 25 | 100.0% | 0.0% | 0.0% |
| total_debt | 25 | 100.0% | 0.0% | 0.0% |
| total_equity | 25 | 100.0% | 0.0% | 0.0% |

Buyer screening criteria against the buyer truth table (a criterion the system did not return counts as unknown):

| Metric | Value |
|---|---|
| Agreement with buyer truth (n=1600 cells) | 0.702 [0.679, 0.724] |
| Predicted met although not met | 0.002 [0.000, 0.005] |
| Unknown rate | 47.2% |
| Accuracy where a status was given | 99.8% |

> Limitations. (1) Data is synthetic and templated: absolute scores are optimistic and say little about real documents; only differences between systems under identical conditions are informative. (2) The same author wrote the generator and the system, so design assumptions may leak into both. (3) The offline dense retriever is LSA, not a neural model; neural results are reported separately when produced. (4) Tier weights are hand-set priors, ablated, not learned. (5) The constructed judge labels are validated on a small hand-labelled sample only. (6) No production traffic, no clinician-grade blind review equivalent, no user study. (7) Bootstrap intervals assume exchangeable queries; the cluster bootstrap is a sensitivity check, not a proof.

## 7. Judge calibration

_Basis: OFFLINE MOCK BASELINE, not an LLM result. Components: judge=real._

Judge labels against the constructed labels of the adversarial test split, 1400 claims pooled.

| Statistic | Value [95% CI] |
|---|---|
| Cohen's kappa | 0.888 [0.863, 0.912] |
| Linearly weighted kappa | 0.849 [0.815, 0.879] |

Confusion matrix (rows constructed, columns judge: supported, partial, unsupported):

|  | supported | partial | unsupported |
|---|---|---|---|
| constructed supported | 220 | 0 | 0 |
| constructed partial | 0 | 229 | 1 |
| constructed unsupported | 80 | 0 | 870 |

Kappa per seed:

| Seed | Kappa |
|---|---|
| 1234 | 0.877 |
| 1 | 0.903 |
| 2 | 0.890 |
| 3 | 0.896 |
| 4 | 0.876 |

Hand labels: not labelled yet.

Self-preference control: with the mock provider the same deterministic routine writes and judges; this is stated, not controlled. For a live run, name the writer and the judge model separately.

> Limitations. (1) Data is synthetic and templated: absolute scores are optimistic and say little about real documents; only differences between systems under identical conditions are informative. (2) The same author wrote the generator and the system, so design assumptions may leak into both. (3) The offline dense retriever is LSA, not a neural model; neural results are reported separately when produced. (4) Tier weights are hand-set priors, ablated, not learned. (5) The constructed judge labels are validated on a small hand-labelled sample only. (6) No production traffic, no clinician-grade blind review equivalent, no user study. (7) Bootstrap intervals assume exchangeable queries; the cluster bootstrap is a sensitivity check, not a proof.

## 8. Latency and cost

_Basis: OFFLINE MOCK BASELINE, not an LLM result. Components: search=real, ask=real._

Cost per query: 0.000000 USD. Basis: zero by definition (mock provider). Mean tokens per query: input 0.0, output 0.0. For the deterministic offline configuration the run to run variance of every metric is zero by construction; the across-seed variance is reported with each table.

Latency in milliseconds, test queries, warm in memory store, machine as in the header (the timing block differs between runs):

<!-- TIMING-BEGIN: wall clock, differs between runs -->

| Measure | n | p50 (ms) | p95 (ms) |
|---|---|---|---|
| search A1 | 1188 | 3.52 | 159.76 |
| search A2 | 1188 | 3.64 | 158.22 |
| search A3 | 1188 | 3.67 | 158.48 |
| search A4 | 1188 | 35.21 | 196.73 |
| search A5 | 1188 | 38.71 | 212.84 |
| stage: contradictions | 1095 | 0.28 | 0.50 |
| stage: retrieve | 1188 | 38.60 | 221.36 |
| stage: understand | 1188 | 0.16 | 0.24 |
| stage: verify | 1095 | 1.47 | 3.71 |
| stage: write | 1095 | 1.49 | 4.52 |
| ask, total wall clock | 1188 | 42.30 | 225.23 |

<!-- TIMING-END -->

> Limitations. (1) Data is synthetic and templated: absolute scores are optimistic and say little about real documents; only differences between systems under identical conditions are informative. (2) The same author wrote the generator and the system, so design assumptions may leak into both. (3) The offline dense retriever is LSA, not a neural model; neural results are reported separately when produced. (4) Tier weights are hand-set priors, ablated, not learned. (5) The constructed judge labels are validated on a small hand-labelled sample only. (6) No production traffic, no clinician-grade blind review equivalent, no user study. (7) Bootstrap intervals assume exchangeable queries; the cluster bootstrap is a sensitivity check, not a proof.

## 9. Regression replay

_Basis: OFFLINE MOCK BASELINE, not an LLM result. Components: ask=real._

Regression cases replayed: 0 cases (the `eval/regression/` directory is empty).

| Cases | Passed | Failed |
|---|---|---|
| 0 | 0 | 0 |

> Limitations. (1) Data is synthetic and templated: absolute scores are optimistic and say little about real documents; only differences between systems under identical conditions are informative. (2) The same author wrote the generator and the system, so design assumptions may leak into both. (3) The offline dense retriever is LSA, not a neural model; neural results are reported separately when produced. (4) Tier weights are hand-set priors, ablated, not learned. (5) The constructed judge labels are validated on a small hand-labelled sample only. (6) No production traffic, no clinician-grade blind review equivalent, no user study. (7) Bootstrap intervals assume exchangeable queries; the cluster bootstrap is a sensitivity check, not a proof.
