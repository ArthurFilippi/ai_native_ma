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

## D10. Extra truth file `truth/aux.json`
- Context: `truth.py` has no place for the exact span of every planted occurrence, the absent terms of unanswerable questions, the reference date or the deal economics, and `verify` must re-derive support sets and absence.
- Choice: one sidecar `truth/aux.json` (not a schema in `truth.py`): `occurrences` per fact id, `absent_terms` per unanswerable id, `reference_date`, freshness windows, `deal_economics`. Consumers may ignore it.
- Alternative: widen `Fact`. Rejected: `truth.py` belongs to the orchestrator. Cost: one more file to keep in step.

## D11. Reference date for staleness is stated in `generator_version`
- Choice: freshness is measured against the fixed date 2025-06-30. `GenerationParams` forbids extra fields, so `params.json` carries it as `generator_version = "synth-1.0;reference_date=2025-06-30"` and `aux.json` repeats it. `core` must pass this date as "today" when it flags stale claims, otherwise every source looks stale (request in `BLOCKERS.md`: add `reference_date` to `GenerationParams`).
- Windows: press 180 d, deal documents 540 d, filings 730 d. Other document types have no window and are never stale.

## D12. Page text conventions of the parsers
- Choice: page text is blocks joined by a blank line, table rows joined by a newline and cells by ` | `. PDF: wrapped lines are rejoined with one space, a gap larger than 1.9 times the font size starts a paragraph, bold is a heading, Courier is a table, the oblique running header (the visible synthetic mark) is dropped from the text. DOCX pages end at explicit page breaks, XLSX has one page per sheet, TXT pages end at a form feed; formats without breaks close a page at a block boundary after 4000 characters. A heading directly above a table is part of the first table chunk.
- Cost: a PDF that does not follow the writer's conventions is parsed less faithfully (acceptable for the synthetic corpus, documented limit for real PDFs).

## D13. Contradiction keys and the stronger side
- Choice: facts are grouped by (entity, metric, period) over documents with status `current`. Two or more documents that agree within 0.5 percent form a `consistent_control`, otherwise a `contradiction` listing every fact of the key. Superseded and withdrawn documents never take part in these groups, they get their own `superseded` or `withdrawn` entry paired with the replacement document. `verify` asserts that no multi-document key is missing. `stronger_document_id` is the lowest tier number, ties broken by the later date (informative only).
- Query relevance: 2 for the support chunks of the gold facts, 1 for the support chunks of other current facts with the same key. A contradiction query has every fact of the key as gold.

## D14. Integer arithmetic for the financial model
- Choice: the Aurora model and the KPI truth come from integers in tenths of EUR m, so every printed cell and every computed KPI (margins, net debt, leverage, coverage) is exact. Percent facts in prose are rounded to one decimal of the exact ratio. KPI ids are the legacy ids (20 of the 62), units written `EUR m`, `%`, `x`.

## D15. Buyer layer sits in the general layer
- Choice: buyer documents have `deal_id = null` and `entity_id = buyer id`, visible to every user like the knowledge base. Buyer truth is derived for Aurora only (`deal_aurora`). Rules are in `docs/DATASET_CARD.md`; `verify` re-derives sector, geography, size, regulatory, activity, ticket, lifecycle, EV ratio, bandwidth and antitrust statuses from the stored buyer documents, facts and news items, not from the generator's structures.

## D16. Seed 1234 anchors
- Choice: for seed 1234 only, Aurora keeps the specification numbers (FY2024 revenue 182.4, FY2023 168.0, gross margin 38.5 percent, largest customer 17 percent, trade press 179). Other seeds draw all numbers from the seed. The structure (which documents state which facts, which keys conflict) is identical for all seeds.

## D20. Retrieval engine object and index cache
- Context: BM25 and LSA are fitted on the candidate set, a run of hundreds of queries must not refit.
- Choice: `RetrievalEngine` caches fitted indexes by a fingerprint of the candidate chunks and the index settings (LRU of 8). `search`, `search_detailed` and `ask` take an optional `engine=` keyword (an addition to INTERFACES); without it a throwaway engine is built. The eval adapter should create one engine per run and pass it.
- Alternative: a module level cache (forbidden global state). Cost: callers must pass the engine to benefit.

## D21. Score scale of the five systems
- Choice: `final_score` is in [0, 1] for every system. A1 is `bm25 / (bm25 + 10)`, A2 the cosine clipped at 1, A3 the RRF score divided by its ceiling `sum(w) / (k + 1)`, A4 and A5 use `relevance = 0.8 * rerank + 0.2 * rrf_norm`, and A5 multiplies by tier, recency and status and adds the corroboration bonus (spec section 7). All constants live in `RetrievalConfig`. Components also carry `relevance` and `status`.
- Reranker features: coverage, phrase, numbers, metric, period and `fact` (the passage states the asked metric as a number for the asked period, so "17 percent of FY2024 revenue" no longer beats "revenue of EUR 182.4 million"). Without the fact feature the tiny corpus ranked the wrong chunk first under every system.
- Alternative: raw BM25 scores. Rejected: a single `tau` could not mean the same thing across systems.

## D22. Reference date for recency and staleness
- Choice: `as_of` is the newest publication date among the candidates (or `RetrievalConfig.as_of`), never today's date, so results are reproducible and independent of when the corpus is queried. Undated sources get recency 0.5.
- Cost: on a corpus whose newest document is old, nothing looks stale relative to the real calendar.

## D23. Withdrawn, superseded and stale handling
- Choice: under A5 withdrawn hits are removed from `hits` and listed in `SearchResult.withdrawn`; the pipeline drops withdrawn passages for every system, so the writer never sees one. `Flag.WITHDRAWN` on a claim means a withdrawn document spoke to the same (metric, period) and was excluded; it is never a citation. If a topic has only withdrawn evidence the answer says `withdrawn_only`. A claim whose citations are all superseded gets `Flag.SUPERSEDED`, and superseded or withdrawn documents never form a contradiction. Stale claims are kept and flagged, so `MissingInfo.reason = "stale_only"` is never produced.
- Cost: a claim with both a current and a superseded source is not flagged.

## D24. Abstention gate and provisional tau
- Choice: abstain when no usable passage reaches `tau` or no verified claim remains. The gate compares `tau` with the retrieval relevance (`abstain_score="relevance"`), not the final score, because tier and recency weights express trust, and an old source must produce a flagged claim, not an abstention (spec section 7: never hide a stale claim). `abstain_score="final"` is available for the ablation.
- `PipelineConfig.tau` is a plain field, provisional default 0.25, hand set on the tiny corpus only. At merge time the orchestrator calibrates it on the DEV split: collect the best support score per dev query (`ainma.pipeline.abstain.support_score` over the retrieved hits, 0 when nothing is retrieved), call `calibrate_tau(answerable, unanswerable, max_false_abstention=0.10)`, freeze the returned `tau` and report its `false_abstention` and `correct_abstention`.
- Cost: until then the false and correct abstention rates are not measured.

## D25. Writer, citations and verifier
- Choice: the model returns passage numbers and quotes, code builds `Citation` (page based offsets, D04). A quote is located exactly, or up to whitespace, in which case the real chunk slice becomes the quote; anything else rejects the evidence, quotes under 10 characters too. The summary is built by code from the verified claims. The verifier runs verbatim and offsets, then `numeric_match`, then the judge, and stops at the first failure; `partial` fails the judge check. Years count as numbers, so an altered period is caught by the judge's metric and period binding when the quote holds several periods.
- Cost: a claim whose quote omits the period is dropped when the claim names it.

## D26. Contradictions
- Choice: facts keyed `(entity, metric, period, unit)` with entity `chunk.entity_id or deal_id`, extracted from the cited quotes through the `extract_facts` task. Values within 0.5 percent form one side, so agreeing documents share a side; sides are ordered strongest first (tier weight times recency). A document that is not independent of every document of the other side (same sha256, `superseded_by` link) does not create a conflict.
- Cost: two different companies mentioned inside one deal share an entity key, a possible false positive on hard negatives.

## D27. Mock tasks are rules, not a model
- Choice: understand (clause split, prior period for growth questions), extractive writer (sentence with the asked metric as a number and the asked period, plus one INFERRED growth claim), judge (number match, metric and period binding, proper noun check, word coverage), extract_facts (rule extractor). `kpi_parse` stays unregistered (D05). Money is reported in millions, bare numbers as written.
- Cost: table chunks are not parsed by the rules (only prose sentences), and paraphrases that avoid the metric vocabulary are missed by design; this is the offline baseline, not an LLM result.

## D28. Live providers
- Choice: `httpx` clients for Gemini (`generateContent`, JSON mime type) and OpenAI (chat completions, JSON mode); the JSON schema is embedded in the system prompt; retries on 429 and 5xx; no key in URLs or errors. Prices live in `llm/providers/prices.json` and are all null with null `as_of`, so `cost_usd` stays null until the owner fills them. Defaults `gemini-2.5-flash` and `gpt-4o-mini`, overridden by `LLM_MODEL`. The response fixtures under `tests/fixtures_core/recorded/` were written by hand in each API's documented shape, not captured from live calls. `build_live_llm(settings)` is ready; `factory.build_llm` still has to call it.
- Cost: real response quirks are untested until a key is used.

## D29. Answer log and trace conventions
- Choice: `data/cache/answers.jsonl` lines hold `id`, `logged_at`, `question`, `config_hash`, `dropped` (claims rejected by the writer or the verifier, for verifier ablations) and the full `answer`. Answer ids are a hash of user, deal, question and config. `stage_latency_ms` has no total key (sum the stages). When the mock replaced a failed live call, `Trace.provider` says so. mypy ignores for scikit-learn and fastembed imports are local (BLOCKERS.md).

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
