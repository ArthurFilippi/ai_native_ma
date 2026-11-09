# Decisions

One short entry each: context, choice, alternative, cost.

## D01. Legacy boot test (phase A, time boxed)
- Context: audit section 6 lists seven static breakage hypotheses for `valo-mvp4/backend`.
- Test: copied the backend to a scratch directory excluding `.env*`, `uploads/` and the old virtual environment, ran `uv sync --python 3.12`, then imported `main` with a dummy database URL.
- Result: dependencies resolve from `uv.lock` and the app imports. Hypothesis 4 (non portable virtual environment) is confirmed and fixed by `uv sync`. Hypotheses 1 and 2 (hosted embeddings, manually started pgvector database) cannot be exercised without secrets and a database, so they stay unconfirmed and are treated as true: the new line has local embeddings and a SQLite default. Hypothesis 6 (no tests) is confirmed by inspection. The others are not testable statically and are not pursued.
- Choice: no further legacy debugging. Port only data (KPI definitions), ideas (source object, RRF, screening rules) and rebuild the rest.
- Alternative: fix the legacy line. Cost of the choice: code is rewritten rather than repaired.

## D02. Contracts are a verbatim copy of the specification
- Choice: `src/ainma/contracts.py` is spec section 5 unchanged. `ruff` ignores UP042 for that file only so the copy stays verbatim.
- Cost: `DocumentMeta` has a computed `tier` field that appears in `model_dump()` but is rejected on input by `extra="forbid"`. Serialise with `model_dump(exclude={"tier"})` when the result must be validated again (the store does). API responses keep `tier`.

## D03. Store scope semantics
- Context: the spec protocol takes `deal_id: str | None` and an access predicate.
- Choice: `candidates(access, deal_id=X)` returns chunks of deal X plus the general layer, each only if the access context allows it. `deal_id=None` returns the general layer only. A user without membership therefore gets zero chunks of any deal and still sees the general layer.
- Alternative: no scope means every allowed deal. Rejected: a question is always asked in one deal or in the general layer.
- Extra methods versus the spec protocol (`put_user`, `put_deal`, `put_membership`, `get_document`, `get_deal`, `list_deals`, `list_users`, `close`) are needed by the loader and the API.

## D04. Offsets are an invariant of the store
- Choice: `put_chunks` rejects any chunk whose text is not exactly `page_text[char_start:char_end]`, and any chunk whose `deal_id` differs from its document. Table chunks must therefore be rendered into the page text. Citation offsets are `chunk.char_start + chunk.text.index(quote)`.
- Cost: parsers must produce page text first and chunk it second.

## D05. Mock provider and KPI parsing
- Choice: the mock implements tasks by name through `MockLLM(handlers)`. Routines live in `llm/providers/mock_tasks.py` (owned by `core`). KPI parsing in mock mode is a regex routine inside `kpi/` (owned by `biz`), so the two agents never write the same file.
- Cost: the mock KPI parser is not reached through `LLM.complete_json`.

## D06. Commit attribution
- Context: the harness suggests a co-author trailer, while `CLAUDE.md` and the master prompt forbid any attribution.
- Choice: no trailer, no tool mention in commits or in the README outside the provenance note. The repository instruction takes precedence.

## D07. Generated data in git
- Choice: generated corpora are git-ignored except `data/synthetic/1234/truth/`. `make data` regenerates everything from the seed, byte for byte.
- Alternative: commit all five seeds. Rejected for size.

## D30. Evaluation units, splits and pooling
- Context: five independent seeds, each with its own queries; the plan asks for mean and standard deviation across seeds and for bootstrap intervals.
- Choice: every table reports the test split only. The dev split is used for one thing, choosing `tau`. Intervals pool the units of all seeds, the unit being a (seed, query), (seed, claim) or (seed, KPI cell), next to the per seed table and the mean and standard deviation across seeds. The cluster for the cluster bootstrap is (seed, source document of the first gold fact).
- Alternative: per seed intervals only. Rejected: with 100 or so queries per seed they are wide, and the seeds are independent datasets, so pooling is legitimate.
- Cost: pooled intervals understate seed to seed variation of the generator; the standard deviation across seeds is printed beside them for that reason.

## D31. One representation for every bootstrapped metric
- Choice: a metric is a `Sample` (numerator and denominator per unit), so a mean of per query values and a ratio of counts (citation precision over claims) use the same code. A resample is a vector of multiplicities, so paired comparisons share the resamples by construction and the cluster bootstrap is the same machinery. The two sided p value is `2 * min(share of differences <= 0, share >= 0)`, floored at `1 / (resamples + 1)`; Holm is applied over the ten system pairs of each retrieval metric.
- Alternative: resample indices per system. Rejected: it breaks pairing.
- Cost: statistics that are not ratios of sums (kappa, F1, precision of contradictions) go through the slower `bootstrap_function`.

## D32. Which score `tau` is compared with
- Context: the plan says "best final passage score"; the core pipeline thresholds the retrieval relevance (its D24) so that an old source still yields a claim carrying the stale flag.
- Choice: the harness chooses and reports `tau` on the same score the pipeline compares with `tau`. The adapter reads that basis from `PipelineConfig.abstain_score` and exposes it as `RankedChunk.support`; the report says which basis is in use. `tau` is the (m+1)th smallest dev answerable score with `m = floor(0.10 * n)`, so at most 10 percent of dev answerable queries fall below it; it is then frozen and the full pipeline is rerun at that value on the test queries (end to end rates), next to the score rule rates and the threshold curve.
- Alternative: always the final score. Rejected: the number would not describe the system that abstains.
- Cost: a pipeline that changes its basis changes the meaning of `tau`; the configuration hash includes the basis.

## D33. Adapter, stubs and what a stub report means
- Choice: `evaluation/adapter.py` is the only importer of `search`, `ask`, `run_screening`, `extract_kpis`, of the configuration classes, of the verification checks and of the judge schemas, all through `importlib`. A missing target is replaced by a deterministic lexical stub (`stubs.py`) and the report header, the banner and every section name it. `--smoke` forces the stubs on a tiny built-in corpus. The judge is called through the pipeline's own `JudgeRequest`, `JudgeResult` and `JUDGE` prompt so that the calibration measures the judge the pipeline uses. One `RetrievalEngine` is shared by a run so fitted indexes are reused (warm numbers, stated). The pipeline answer log is disabled during evaluation.
- Cost: the targets table in `adapter.py` must follow renames in other modules; a rename shows as `stub` in the report, never as a silent change.

## D34. Run dependent parts of RESULTS.md
- Context: the brief asks for an identical report on rerun except date, commit and machine, but latencies are wall clock.
- Choice: two delimited blocks: the metadata block (date, commit, machine) and the timing block (latency table). `strip_run_dependent` removes both and a test asserts the rest is identical across two runs, also under different `PYTHONHASHSEED`. `latest.json` holds the same numbers.
- Cost: one block more than the brief names.

## D35. Metrics that must not grade the system with its own code
- Choice: number extraction, the verbatim check and the numeric coverage used by citation precision, recall and the unsupported-claim rate live in `metrics/numbers.py` and do not import the pipeline verifier. The verifier quality on adversarial claims deliberately uses the pipeline checks, because that is the object under test.
- Cost: two number parsers exist in the repository; their disagreements would show up as a nonzero unsupported-claim rate after verification.

## D36. Scoring rules for contradictions and flags
- Choice: a planted pair is detected when the answer to its question holds a contradiction whose cited documents include at least two documents of the pair; a consistent control is a false positive under the same rule. F1 is `2TP / (2TP + FP + FN)`. Superseded and withdrawn cases have four outcomes (flagged, reported as contradiction, cited without the flag, not surfaced) and are never mixed into recall. The question is the truth query text, or `What is <subject>?` when the truth names none.
- Cost: a contradiction between two other documents of the same answer is not counted either way.

## D37. KPI and screening scoring
- Choice: a missing KPI value is not correct (accuracy denominator is every truth cell) and is reported as the safe error beside the wrong-value rate. Citation validity accepts a value up to a power of 1000 and 0.5 percent (`EUR 182.4 million` against `182,400 thousand`). Screening cells the system did not return count as `unknown`.
- Cost: scale tolerant validity can accept a quote that has the right digits at the wrong scale; the cell accuracy catches the wrong value itself.

## D38. Blind hand labelling protocol
- Choice: the CSV holds the claim, the passage and an empty column; the key file holds the constructed label and, for scoring, a copy of claim and passage, so scoring needs no corpus. The judge output is never stored: `--score` computes it at scoring time with the current adapter and records whether the judge was real or stub. Sampling is a round robin over (constructed label, perturbation) strata with neutral item ids. The sample is drawn from every split; scoring writes `label_scores.json`, which the report reads (`not labelled yet` until a human fills the column).
- Cost: the key file reveals the labels to anyone who opens it before labelling.

## D39. Seeds on the command line and sensitivity sweeps
- Choice: a single `--seeds N` with N from 1 to 5 means the first N of `1234 1 2 3 4`; several numbers or `--seed-list` name seeds explicitly. The three sweeps (tier prior uniform, RRF weights, recency half-life) are discovered from the retrieval configuration (`ranker.tier_weights`, `rrf_weights`, `ranker.half_life_days`) and run on A5 only; a sweep whose field is absent or has an unexpected shape is printed as `not run` with the reason.
- Cost: a seed list with a single seed between 1 and 5 needs `--seed-list`.
