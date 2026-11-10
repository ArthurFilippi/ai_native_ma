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
- Status: superseded. `factory.build_llm` now calls `build_live_llm` for `gemini` and `openai`; the live providers are still tested on recorded fixtures only.
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

## D40. Scoring edge rules (biz)
- Context: `scoring_vectors.json` fixes the formula, not three edge cases: cards that failed stage 1, criteria that do not apply to a buyer type, ties after float arithmetic.
- Choice: a card with `stage1_passed=false` is unscored (score `None`, coverage 0, empty contributions, no dealbreakers, rank `None`) and listed after the ranked cards. A criterion without a result on a card does not apply: its weight leaves both sums, so a strategic buyer is not penalised for having no `ticket_fit`. `contributions` has a key for every criterion (0.0 when unknown, not met or not applicable). Scores and coverage are compared after rounding to 9 decimals when ranking. Dealbreakers keep their flag when their weight is overridden to zero. Hand-computed vectors for these rules are in `tests/fixtures_biz/scoring_vectors_extra.json`; the TypeScript twin must follow them.
- Alternative: score failed cards on their prefilter results only. Rejected: a score built from prefilter criteria alone reads as a verdict.
- Cost: the twin carries three rules the shared vector file does not test.

## D41. Where the buyer universe comes from (biz)
- Status: done. The store has a buyers table (`put_buyer`, `list_buyers`), the loader fills it, and callers no longer pass the list.
- Context: the `Store` interface has no buyer table and `run_screening(request, store=, access=, llm=)` has no buyers argument.
- Choice: `run_screening` takes an optional `buyers=` list and otherwise calls `store.list_buyers()` when the store has it, and raises `BuyerUniverseUnavailable` when neither exists. `screening.load_buyers(seed_dir)` reads `truth/buyers.json`. Request to the integration owner in `BLOCKERS.md`: add `put_buyer` and `list_buyers` to the store and let `load_corpus` fill it, or pass `buyers=` in the API and the evaluation adapter.
- Alternative: read `data/synthetic/<seed>` from settings inside `run_screening`. Rejected: hidden global state.
- Cost: until that wiring exists the callers pass the list themselves.

## D42. Prefilter semantics (biz)
- Choice: the structured profile is the evidence of a prefilter criterion. A filter that the request does not set gives `unknown` ("not evaluated"), never `met`; `sector_focus` uses the deal sector when the request sets none. Sector matching is exact, containment, or half of the word stems in common. A buyer passes stage 1 when no prefilter criterion is `not_met`. Passers are ordered by prefilter score, then coverage, then buyer id; the first `stage2_top_n` go to stage 2. The textual confirmation of the sector (a cited sentence) is retrieved only for those buyers, to bound retrieval cost. Buyers beyond the cut keep `unknown` ("Not evaluated") on the deep criteria, so coverage shows it.
- Cost: with many buyers passing every prefilter, the cut among ties is by id. Raise `stage2_top_n` to cover the universe when measuring.

## D43. Deep stage parameters (biz)
- Choice: the indicative cheque is `EBITDA x 8.0 x 50%` where EBITDA is the latest positive value extracted from the deal's documents (cited), 8.0 is `ev_ebitda_multiple` and 50% is `equity_share_of_ev`, both placeholders in `ScreeningParams` and quoted in every rationale. Without a sourced EBITDA, `ticket_fit` and `ev_ratio` are `unknown`. The buyer EV of a strategic buyer is its market capitalisation (`size_eur_m`). Ticket: below 5% or above 40% `not_met`, 10% to 25% healthy, the rest `met` and said to be outside the healthy band. EV ratio: above 60% `not_met` (dealbreaker), above 40% `met` with the word "transformational" in the rationale. A cited passage that states another fund size than the profile sets `conflicting_evidence`; the profile figure is the one used.
- Alternative: use the stated valuation of the deal when one exists. Not done.

## D44. Deep rules over text (biz)
- Choice: rules are regex over retrieved passages, only from `current` documents (superseded and withdrawn documents are not evidence), about the buyer by entity id or by name. Fund lifecycle: investment period end date (year only means 1 July), at least 2.0 years remaining. Recent activity: an acquisition sentence in the target's sector within 36 months of `as_of`; acquisitions found but none similar or recent is `not_met`, none found is `unknown`. Integration bandwidth: at most 2 acquisition documents in 24 months (a lower bound, one count per document). Antitrust: buyer share known and either the target share known (combined at or above 35% is `not_met`) or the buyer alone at or above 35%; anything else is `unknown`. Regulatory and FDI: a constraint phrase is `not_met` (negated phrases such as "no state ownership" are not constraints), a clean ownership phrase is `met`, otherwise `unknown`. `as_of` defaults to the latest publication date visible in the deal scope.
- Cost: wordings the generator does not use stay `unknown` (the safe error). Recall is measured by `make eval`, not claimed here.

## D45. KPI reading and verification (biz)
- Choice: the mock reader is `kpi/parse.py`: table rows (`label | v1 | v2`, one number per header period, header carried over from an earlier chunk of the same page when a table was cut) and sentences (a KPI wording, the next number of a compatible unit kind, its period). Money is normalised to EUR millions (`182.4`, `182,4`, `EUR 1.2 billion`, thousands by header), percentages and ratios by their sign or word, counts must be integers. A candidate is kept only if its value appears in its own quote (`value_in_quote`, factors 1e3 and 1e6 tolerated for header scales). Compute KPIs go through the safe evaluator from their inputs; when an input is missing the stated value is looked up instead, otherwise `missing`. The first candidate in retrieval rank order wins, so a conflicting low tier source does not override a higher ranked one; the conflict itself is not surfaced by `KpiValue`.
- Cost: the first value wins; no disagreement flag on KPIs.

## D46. Retrieval seam and shared helpers (biz)
- Choice: `kpi/sources.py` holds `SearchFn` (the shape of `ainma.retrieval.search`), `resolve_search()` (lazy import, loud error when missing) and `CitationBuilder` (citation offsets by code, D04); `screening/evidence.py` re-exports them. They live under `kpi/` because `screening` imports `kpi`, never the reverse. Entry points take an optional `search=` for tests; tests use `tests/fixtures_biz/keyword_search.py`.
- Cost: one import indirection until `core` is merged and the defaults are exercised against the real retrieval.

## D47. Connectors (biz)
- Choice: `run_market_intel` ingests every item of the feed (the deal's and the buyers') into the deal space as one page documents with `entity_id` set to the item entity, so screening finds buyer news by entity. Document id is a hash of connector, entity, title and date (rerun replaces, never duplicates). The SYNTHETIC mark is in the page text but not chunked. Items must be press articles or releases. The optional Tavily connector was cut (first item of the cut order); paid connectors are interface-only (`connectors/base.py`).
- Cost: the CLI uses the configured store (`SQLITE_PATH`), so `make demo` must run it against the same file as the API.

## D48. KPI definition port (biz)
- Status: done. The data merge happened and the definitions are in `kpi/definitions.py`.
- Choice: 30 definitions kept from the legacy 62 (income statement, cash flow, balance sheet, returns, headcount, customer concentration), same ids, formulas and `depends_on`. Units are `EUR m`, `%`, `x`, `count`; all KPIs are annual with periods `FY2020` to `FY2024` by default. To prune to the 20 KPIs of `kpi_truth.json` after the `data` merge.

## D50. API wiring through one guarded module
- Status: superseded. `api/services.py` now calls the real modules directly; there is no stub fallback and no import at call time.
- Context: core, biz and connector modules are written in parallel and may be absent on a branch.
- Choice: `ainma/api/services.py` is the only importer. It resolves `ainma.pipeline.ask`, `ainma.screening.run_screening`, `ainma.kpi.extract_kpis` and `ainma.connectors.run.run_market_intel` with `importlib` at call time. A missing module or function means the example payloads of `ainma/api/examples/` answer and `X-Ainma-Backend: stub` says so (`real` otherwise). A module that exists but fails on one of its own imports raises instead of being hidden.
- Alternative: import at start-up. Rejected: the stub would be silent and the API would not start on a partial branch.
- Cost: a stub answer is visibly different from a real one only through the header and the UI badge.

## D51. Not found, not forbidden
- Choice: every `/deals/{id}...` route resolves the deal through `store.get_deal(deal_id, access)` first, as a FastAPI dependency, so a non-member (or a missing deal) gets 404 before the body is even validated. The passage endpoint relies on the access predicate inside `get_chunk`, `get_document` and `get_page`. `POST /screening` returns 422 when the body names another deal than the path.
- Cost: an unknown deal and a hidden deal are indistinguishable, on purpose.

## D52. Passage response and highlight offsets
- Choice: `GET /passages/{chunk_id}?page=true` returns `chunk`, `document`, `page_text` and `highlight_start/end` equal to the chunk offsets, so `page_text[start:end] == chunk.text`. The citation span (the quote) lies inside that range and is the text marked in the UI. The client trusts the citation offsets only when the page text at those offsets is the quote, then searches the quote in the chunk, then marks the whole chunk and says it is inexact.
- Cost: one extra field pair that is redundant with the chunk, kept so clients need no knowledge of chunk semantics.

## D53. Demo users endpoint
- Choice: `GET /users` needs no header (the switcher has to list users before one is chosen) and exposes only id and name. It is part of DEMO_AUTH and goes away with real authentication.
- The `X-User-Id` scheme is declared as an OpenAPI API key so the docs page shows it.

## D54. Stub answer carries the request
- Status: superseded. The stub answers were removed with the stub fallback (see D50).
- Choice: the stub ask fills `user_id`, `deal_id` and also `question` from the request, so the question echo on screen is the one asked. It picks the contradiction example when the question contains "revenue" (case-insensitive) and the abstention example otherwise.

## D55. Market intel seed directory
- Status: partly superseded. The seed directory rule stands; there is no stub, and the response header `X-Ainma-Backend` was removed.
- Choice: `run_market_intel` needs a `seed_dir` and settings have no such field, so the API passes `data/synthetic/<settings.seed>`. The stub ingests nothing and returns 0.
- Cost: the path is relative to the working directory of the server.

## D56. Web stack
- Choice: Next.js 16 (App Router, Turbopack), React 19, TypeScript 5.9 strict, ESLint 9 with `eslint-config-next`, Vitest 5 with jsdom and Testing Library. All versions pinned exactly, lockfile committed. TypeScript 7 and ESLint 10 were not used because the Next lint config targets ESLint 9.
- The browser level one-click check is a Vitest and jsdom test (renders the app, clicks one citation, asserts the `<mark>` text and exactly one passage request). A real browser variant exists as `web/e2e/one-click.mjs`, with Playwright deliberately not a dependency.
- Cost: jsdom does not do layout, so scroll position is only checked by the optional browser script. `npm audit` reports moderate advisories in the lint toolchain (`minimatch` through typescript-eslint), not in the shipped bundle.

## D57. Mock mode and shared payloads
- Choice: `web/src/mock/*.json` are committed copies of the fixtures and of `ainma/api/examples/`. A test fails when a copy drifts, `npm run sync-mock` refreshes them. The mock backend serves a page rebuilt around the quote (filler text, quote at its citation offset), labelled synthetic filler.
- The example screening payload has hand-built cards whose scores satisfy the shared scoring rules at the default weights (a test checks it), and raising the antitrust weight swaps the first two ranks so the demo moment works offline.

## D58. Client side scoring
- Choice: `web/src/lib/scoring.ts` implements only the rules in `tests/fixtures/scoring_vectors.json` over all cards it is given, with a criterion missing from a card read as `unknown`. Stage 1 failures are not treated specially. If the Python `score_cards` treats `stage1_passed=false` differently, the vectors and this file must change together.

## D59. UI conventions that carry the principle
- Status encoding without colour: sourced is a solid left rule with a tier chip, inferred a dashed rule with the label "System deduction" and links to the claims it derives from, missing a hollow marker with "Not established by the sources". Flags are text chips. The value contract is a footer element of the Ask screen, compared in a test with `contracts.py`.
- Evidence panel failure is explicit: when the passage cannot be loaded (for example a stub answer whose chunk is not in the store) it says so and shows the cited quote only.

## D70. Evidence is retrieved inside a scope, not filtered after the ranking (quality-biz)
- Context: `search` ranks every chunk the user may see (the deal and the general layer, 200 documents in the generated corpus) and returns ten. A query about one buyer competed with the 39 other buyers, and a question about the deal's revenue competed with the buyers' annual reports. Two measured consequences: the press release or the fund summary of the right buyer was not in the ten (80 percent of deep criteria came back `unknown`), and the revenue of a buyer was returned as the revenue of the deal (a wrong value, on seeds 2, 3 and 4).
- Choice: `kpi/scope.py` provides `ScopedStore`, a read only view over a `Store` that keeps the chunks and documents of one entity or one deal. The access filter stays in the wrapped store's own query. `search` is called on the view through its public signature. Buyer evidence uses the entity scope (a fallback to the whole scope with the buyer name in the text applies only when the buyer has no document under its id); KPI extraction, deal value and target share use the deal scope, which keeps documents with no entity or with the deal as entity (buyer news that the connector files in the deal space is not about the deal).
- Alternative: ask retrieval for an entity filter. Rejected: retrieval belongs to another agent and the store view needs no change there.
- Cost: one index fit per scope on small chunk sets (cheaper than one on the whole corpus); a corpus whose buyer documents carry no entity id falls back to the old behaviour.

## D71. A qualified measure is not the plain KPI (quality-biz)
- Context: `Adjusted EBITDA for FY2024 was EUR 32.8m` (quality of earnings summary) was an alias of `ebitda` and won over the plain EBITDA of the model (31.8): a wrong value of 3 percent, found by reading raw outputs.
- Choice: a label preceded by `adjusted`, `normalised`, `underlying`, `pro forma`, `run rate`, `estimated`, `forecast` or `budgeted` is not read as the KPI, in sentences and in table rows. The aliases `adjusted ebitda` and `adjusted ebitda margin` are removed from the definitions.
- Cost: an adjusted figure is never extracted, even when the data room states nothing else (the KPI stays `missing`, the safe error).

## D72. The stated deal value sizes the cheque, the parameters are a fallback (quality-biz)
- Context: D43 sized the cheque as EBITDA x 8.0 x 50 percent, which differs from the value the CIM and the executed SPA state (`priced at EUR 197.1 million`, `Shareholders would receive EUR 169.2 million`): one ticket verdict was wrong because of the placeholder multiple.
- Choice: `stated_valuation` reads the deal documents (current ones only, through the deal scope) for an enterprise value and an equity value. The equity cheque is the stated equity value (the buyer acquires all of it), or the documented share of a stated EV, or, without any stated value, the EBITDA route of D43. The rationale says which basis was used and which numbers are parameters. A sentence with a percentage of the equity value (a break fee) has no amount after the cue and is not read.
- Cost: a stated value is trusted as the rank order of retrieval gives it; two disagreeing current documents are not flagged.

## D73. Fund and ownership statements (quality-biz)
- Choice: the end of the investment period is read from `investment period ... ends in YEAR`, from `new platform deals/investments ... until YEAR` and from a table or footnote row `Investment period end: YEAR`; a permanent capital structure without a fixed investment period is `met` (no date by which investments must stop). Ownership: `privately held` is not evidence of the absence of state ownership (it says the shares are not traded), so it no longer gives `met`; `privately owned`, `family owned` and a negated constraint (`has no state shareholders`, `no exposure to defense contracts`) do. Constraint phrases now include `exposure to defense`, `defense contracts` and `state shareholders`; a constraint wins over a clean statement and sets the conflict flag.
- Cost: the wordings are a closed list; others stay `unknown`.

## D74. What an acquisition is in the target's sector (quality-biz)
- Context: the sector was looked up in the whole chunk with word stems, so the filler sentence of a press release (`add-on opportunities in industrial components`) or the buyer's name (`Draix Industries`) made a medical devices deal similar. A news item has its title and its body in two chunks, and only the title matched.
- Choice: the sector must appear in the acquisition sentence, or in the next sentence when it starts with `The target`, with every word of the sector present (`sector_regex`, order free for two words) and the buyer's own name removed. When a document has several passages about the acquisition, the one that places the target in the sector is kept and its quote spans both sentences. Recency uses days over 30.4375 instead of calendar months.
- Cost: a sector described in a third sentence is not found (`not_met` when other acquisitions are reported, `unknown` otherwise).

## D75. Market share wordings, antitrust stays unknown without the target (quality-biz)
- Choice: `controls|holds|commands|accounts for N% of ... sales|market|segment` is read as a share besides `market share ... N%`. A buyer share below the 35 percent flag with no target share in the deal documents stays `unknown`: the combined share is not established, and nothing in the generated deal documents states the target's share. The buyer truth table calls these `met`; this is the largest remaining gap by design and is reported, not closed.
- Alternative: `met` when the buyer alone is below the flag, with the target share noted as unknown. Rejected: it turns a missing number into a verdict, the exact error the criterion exists to avoid.

## D76. Why the harness measures 77 percent unknown, and what is by design (quality-biz)
- Status: superseded by D80. The harness now passes the filters, `stage2_top_n=50` and the news feed; the 77 percent unknown figure describes the old default request only.
- Context: the evaluation harness screens with `ScreeningRequest(deal_id)` only: no filters, `stage2_top_n=10`, and no market intelligence ingestion. The buyer truth is defined for all 40 buyers and for the Aurora region and size.
- Findings, measured on seeds 1 and 2: with no geography and no size filter 80 of 320 cells are `unknown` by D42; with the default top 10 only the first ten buyers that pass stage 1 reach stage 2; the 18 buyers that fail the sector prefilter never reach it (D40); acquisitions that were not published as a press release exist only in the simulated news feed, which the harness does not ingest, so `recent_activity` and `integration_bandwidth` see a subset (a lower bound, which can turn a `met` into a wrong `met`).
- Choice: the requests for the harness are in `BLOCKERS.md` (pass the Aurora region and size range as filters, `stage2_top_n=50`, ingest the news feed before screening, as `make demo` does). The module keeps its semantics; agreement over the cells that were evaluated is the measure of reading quality.

## D77. Boundary effects are kept (quality-biz)
- Choice: the reference date of the recency rules is the latest publication date visible in the deal scope (D44), not the generator's fixed `reference_date`. An acquisition 36.0 to 36.7 months before the generator's date but inside the window of the system's date gives one `met` against a truth `not_met` per corpus (about 0.3 percent of cells). Not tuned away: `ScreeningParams.as_of` exists for a caller that knows its reference date.

## D60. Evaluation split option and the split of planted cases (core)
- Context: the first honest run only measured the test split, tuning needs a split that may be looked at, and the planted contradiction, superseded, withdrawn and stale cases had no split at all (the plan says "test only"), so any fix tuned on them would have been tuned on the reported units.
- Choice: `python -m ainma.evaluation.run --split dev|test|both` (default `test`). Every planted case is split by the hash of its own id, like queries and judge labels (`harness.in_split`), so a dev run measures dev cases and the default run measures the other cases. `tau` is still chosen on dev queries only, so on `dev` and `both` it is applied in sample; a non test split prints a banner and the header names it. The oracle test of the smoke fixture runs on `both` because its three planted cases fall into different splits.
- Cost: the number of planted cases in the default report is about 70 percent of the earlier one (the saved first run used all cases), so contradiction counts are not comparable one to one with that run. All tuning below used seeds 1 and 2 and the dev split only; seeds 1234, 3 and 4 and every test unit were first read in the final run.

## D61. The question names an entity: gate, not feature (core)
- Context: a question asked inside a deal was answered with passages of buyer annual reports of other companies (shared words such as `revenue FY2024`), and `Aurore Components` was confused with `Aurora Components`.
- Choice: `retrieval/entities.py` reads the capitalised phrases of a question (not question words, metrics, periods, months, currencies) and keeps the brand tokens (`Aurora Components` gives `aurora`; descriptors such as `components`, `capital partners` do not tell companies apart). The reranker multiplies its feature mean by `entity_floor + (1 - entity_floor) * share`, where share is the idf weighted share of brand tokens found in the whole document of the passage (title and all chunks), so a chunk that never names its company still counts through its document. An additive entity feature was tried first and was worse (it gave every on-entity passage free credit, dev unanswerable queries scored as high as answerable ones). The pipeline drops passages whose share is below `entity_gate` (0.5). Chunks of documents that name the entity join the reranker window (`entity_expansion`, 40) so a press article that says `Fynex` and little else is not crowded out by other fund summaries. A deal question also gives general layer passages a scope weight 0.7 unless they name the entity (`out_of_scope_weight`).
- Tried and dropped: prefixing the document title to every indexed chunk (`contextual_title`): nDCG@10 of A4 moved by +0.005 and a title only chunk started to match every query about that company; removed.
- Dev, A4 nDCG@10 (seeds 1 and 2): 0.688 before, 0.768 with the gate on the first lexicon, 0.930 at the end of this work with the glossary below. Disclosure: after the first complete run on the test split, reading the failure categories of seed 1234 (read only) showed one bug that dev data did not exercise: the descriptor list was compared with stemmed tokens (`analytics` became `analytic` and was kept as part of the brand, so a press article that says only `Kesent` fell below the gate for `Kesent Analytics`). It was fixed in general (descriptors are compared after stemming, regression test) and the numbers reported are from the rerun; it is the only change made after test results were seen, no threshold moved. Cost: an entity such as `CEO` is read as a name; on the unanswerable queries that is a feature (the share is 0, the pipeline abstains) but it is accidental.

## D62. Glossary of metric phrases, concept tokens, residual coverage (core)
- Context: paraphrases ("turnover", "total sales", "workforce", "borrowings less cash", "earnings before interest, tax, depreciation and amortisation", "operating earnings before depreciation") were not mapped, table cells were not facts, ranges ("equity tickets of A to B") had no reading, and a day of the month ("31 December 2024") became a revenue figure.
- Choice: `retrieval/lexicon.py` is a small glossary of financial terms with a canonical label per metric and a kind (money, percent, count, year, multiple, duration); longest phrase wins, and a quantity is only given to a metric of its kind, which is what keeps `38.5 percent of sales` from being revenue. It was written after reading the phrasing families of the generator, so it is data aware by design but it is a glossary, not per fact rules; limitation (2) of the report applies with more force to the mock numbers. `target_metrics` removes the base of a ratio and conditions (`share of revenue ... largest customer`, `after net debt`). Facts are read from sentences and from table rows under a header that names periods; undated metrics (fund vintage, process length) get the period `static`. BM25 and LSA also read one concept token per metric a text states (`concept_tokens`, flag in `RetrievalConfig`), the offline stand in for what a neural embedder does with paraphrases; the reranker's coverage and phrase features are computed on the residual query without metric, period, date and entity words, which are judged by their own features.
- Dev, A1 BM25 nDCG@10 0.675 to 0.761 with the concept tokens, so A1 is BM25 over concept enriched text; the plain variant is `concept_tokens=False`. Cost: a metric phrase that is ambiguous in real text (`shareholders`, `plants`) can produce a false concept token.

## D63. Source ranker: tempered trust, corroboration times relevance (core)
- Context: the multiplicative form `relevance * tier * recency * status` crushed relevant but old or low tier passages (A5 lost 16 points of nDCG@10 against A4) and the additive corroboration bonus lifted irrelevant passages of other companies.
- Choice: `final = relevance * scope * (tier * recency) ** 0.1 * status + 0.05 * min(n - 1, 3) * relevance`. Status stays outside the exponent, so a superseded passage keeps its factor 0.2 and a withdrawn one stays at 0. The exponent is a configuration field (`trust_exponent`, 1.0 is the spec formula). Dev A5 nDCG@10 by exponent after the entity gate: 0.1 gives 0.953, 0.3 gives 0.899, 0.5 gives 0.884, 1.0 gives 0.856 (A4 is 0.930); with the earlier relevance and the spec formula it was 0.535. A5 above A4 on dev means corroboration and trust break ties among equally relevant passages; it is a dev number and the report states the test one.
- Cost: with a small exponent the trust of a source barely moves the ranking; its job is carried by flags, by the stronger side of a contradiction (which uses the untempered tier weight times recency) and by the stale rule.

## D64. Canonical claims, quotes and claim based contradictions (core)
- Context: the offline writer copied sentences, so a paraphrase ("Turnover climbed to EUR 182.4 million over fiscal 2024") never matched the metric and period words of the question, table facts were not claims, and contradictions needed the period inside the quote, which press sentences and table rows do not carry.
- Choice: the offline writer reads the asked metrics, periods and entity per sub-question, selects facts from the passages (sentences and table cells) and writes one claim per fact in a canonical form (`Aurora Components revenue for FY2024 was EUR 182.4 million.`); the quote is the sentence or the table row, verbatim. The same claim stated by several passages is one claim with up to three citations. A sentence that names another company, a near miss of the asked brand (`Aurore`), or a name in the middle of a sentence that is not a place or a metric (`Senix` for `Ravell`) is never a claim; a figure without a period describes the latest fiscal year before its source was published (an article of February 2025 speaks about FY2024), so it is not offered as evidence for FY2022; without a period in the question the latest stated period is answered. Contradiction facts are read from the claim texts (`collect_claim_facts`), keyed `(entity, metric, period, unit)`, side labels are the amount as the source writes it. `numeric_match(claim, quote, context="")` gained the optional chunk: a quote with no year (a table row) takes the year from the header of its chunk, a quote that states another year is never rescued, and a source that states no year at all leaves the year of the claim unchecked. The growth claim prefers two figures of the same source.
- Cost: claims about disagreeing sources lower citation precision by the metric's definition when the query is not a contradiction query (the second source is not gold); the same is true of a flagged superseded claim. Both are intended.

## D65. Judge: fact by fact, entity conflict on positive evidence (core)
- Context: the first mock judge flagged 66 percent of supported adversarial claims (kappa 0.62) because it required every proper noun of the claim in the quote and treated metric words as coverage.
- Choice: `pipeline/rules.py::judge_support` reads the facts of the claim (metric, period, value) and checks each against the facts of the quote plus the table rows the quote contains (the header comes from the chunk): all verified is supported, some is partial, none is unsupported. A verified claim is unsupported when its brand is missing from the evidence and the evidence names a different company shaped phrase (`Ithis Systems`, `Aurore Components`); evidence that names nobody (a table row) cannot contradict a name. Claims without a keyed fact fall back to the older number, name and word overlap routine. The thresholds were set looking at dev labels only.
- Dev result (the dev labels of seeds 1 and 2): kappa 0.648 to 0.873, false flag rate 0.542 to 0.0, recall of unsupported claims 1.0 to 0.896. The recall loss is the altered entity claims whose chunk names no company (tables, `the company`): a chunk local judge cannot see them, the pipeline avoids the case upstream with the entity gate. Two supported claims about undated press sentences are flagged by the numeric check when the claim names FY2024 and the chunk has no year anywhere; changing that would hide altered period claims, so it stays.

## D66. Superseded passages are surfaced, the writer reads relevance, trust orders it (core)
- Context: a superseded document ranks low by design (status factor 0.2), fell below the top k and was never flagged (flagged 3 of 12 cases); the abstention threshold also filtered every passage, which removed the weaker second source that makes a disagreement visible.
- Choice: `SearchResult.superseded` lists superseded passages below the top k under A5, the pipeline adds them to the writer's candidates, and a claim whose citations are all superseded carries `Flag.SUPERSEDED` (withdrawn documents are unchanged: excluded, flagged through the same metric and period). The pipeline retrieves 20 passages (`PipelineConfig.retrieval.top_k`) and the writer window is the `writer_passages` most relevant ones, ordered by trust (`abstain.writer_window`). `tau` now decides whether a sub-question is covered at all (best passage of the entity matched candidates), and passages above `passage_min` (0.35) reach the writer. The adapter builds the pipeline configuration from the pipeline's own default retrieval list.
- Cost: more claims per answer on questions where old documents exist; the summary shows at most four sentences.

## D67. Abstention: why answerable queries abstained (core)
- Context: first run, end to end false abstention 31 percent against a score rule of 9.7 percent.
- Findings (dev, raw answers): (1) a claim that failed the judge dropped the answer (`Every drafted claim failed verification`): the first judge required the company name in the chunk, which tables and many sentences do not carry; (2) the writer received passages of other companies and found no fact for the asked company; (3) paraphrased questions had no metric, so no fact was selected; (4) the filter `relevance >= tau` applied to every passage, not only to the best one. Fixes are in D61 to D66; no threshold was lowered. Dev end to end false abstention 0.431 to 0.072 and correct abstention 0.95 to 1.0, score rule 0.092 false and 1.0 correct (the entity gate and the residual coverage separate unanswerable questions, which share the corpus vocabulary but not the entity and metric).
- Remaining: paraphrased questions answered from a table chunk have the lowest relevance and are the false abstentions left; `tau` is chosen at 10 percent false abstention on dev by the harness.

## D68. What was tried and did not help (core)
- Title prefix on every chunk (D61): no gain, noise from title only chunks. Additive entity feature (D61): worse than the gate. Spec form trust exponent (D63): kept as a configuration value, not the default. Raising the number of candidates only (`rerank_top` 30 to 60) was not needed once the entity expansion existed and was not kept.

## D69. Adapter and harness changes made for this work (core)
- `Adapter.judge` passes the chunk as context to the numeric check when the check accepts one, as the pipeline does; `Adapter.ask` builds its retrieval configuration from the pipeline default (same list length as the API) with system A5; `RunMeta` has a `split`. Generated corpora can contain stray `name 2.ext` copies (a synchronised folder makes them); they are ignored by a local `info/exclude` rule and must never be committed.

## D80. Screening protocol of the evaluation harness (integration)
- Context: the buyer truth for geography and size is defined against the Aurora region and its size range, and 60 acquisitions exist only in the simulated news feed. A default request (no filters, 10 deep screenings, no news) leaves those cells `unknown` by design, so the measured agreement said little about the screener (0.40 on seed 1, against 0.73 with the demo protocol).
- Choice: the harness screens the way the demo does: filters from `truth/aux.json` (region, EV to 60 x EV), `stage2_top_n=50`, and the simulated feed filed in the deal space first through the adapter (`Adapter.ingest_news`). The numbers come from the system's own inputs, not from the truth answers: the filter values are the deal's stated facts.
- Alternative: keep the default request and report a low agreement. Rejected as a measurement of the protocol, not of the system.
- Cost: the screening agreement is conditional on an analyst who states the deal's region and size. Two limits remain and are reported, not tuned away: antitrust truth cells assume a target share that no document states, and deep truth also covers buyers that fail the sector prefilter.

## D81. Roles are enforced on the two routes that compute or write (integration)
- Context: the independent review found that `Role` was stored in memberships and never read. Spec section 13: a `viewer` reads answers and documents only.
- Choice: `Store.role_in(deal_id, user_id)` returns the role; `POST /deals/{id}/screening` and `POST /deals/{id}/market-intel/run` answer 403 to a viewer (the second one writes documents into the deal). Reading, asking and the passage endpoint stay open to every member. A non member still gets 404 on every deal route. Membership management by a `lead` is not implemented (there is no route for it): memberships come from the data loader.
- Alternative: leave roles unenforced and say so. Rejected: two lines per route and a test are cheaper than a documented gap.
- Cost: `ask` is allowed for a viewer because the answer is a read; if asking should be restricted later, the same dependency applies.

## D82. One frozen abstention threshold, shared by the product and the report (core)
- Context: review finding H1. `DEFAULT_TAU` was a hand set 0.25 ("provisional", D24) that the API, the CLI and the demo used, while the harness chose a different tau per seed on dev (0.5827 to 0.5991) and the README quoted that configuration. The product and the tables described different systems. D24 is superseded by this entry: the threshold is no longer provisional and its rates are measured.
- Choice: `DEFAULT_TAU = 0.595212`, the pooled dev threshold of the five seeds (489 dev answerable queries, (m+1)th smallest best relevance, target false abstention 10 percent), with a comment pointing at `python -m ainma.evaluation.run --calibrate-tau --seeds 5`, which prints the pooled value and the per seed values. The harness evaluates the test split of every seed at that one value (`Adapter.default_tau`, `evaluate_seed(frozen_tau=...)`); stubs and the smoke run, which have no pipeline default, still calibrate on the seed's dev queries. The per seed dev calibration stays as a column of the abstention table, and the report header prints the frozen value, the pooled dev value recomputed in the run and their difference, so drift after a retrieval change is visible. Test queries were never used to choose it.
- Measured at the frozen value (mock, 5 seeds, test split): end to end correct abstention 0.920 and false abstention 0.082, score rule 0.913 and 0.094, abstention precision 0.585 (about four in ten abstentions are on answerable questions), hard unanswerable questions 80.0 percent. The dev false abstention of a single seed at the frozen value ranges from 5.1 to 14.1 percent: one threshold is a little too strict for some seeds and a little loose for others, which the per seed table shows.
- Cost: the frozen value must be recomputed by hand when retrieval changes (the report shows the drift). `tau` is chosen on the score of the whole question, while the pipeline compares it with the best passage of each sub-question (D83), so compound questions are judged slightly differently from how the threshold was chosen.

## D83. Compound questions are decomposed and answered half by half (core)
- Context: review finding H2. "What was Aurora's gross margin and how concentrated is its customer base?" (the demo sentence) returned only the gross margin with no trace of the second half, and "gross margin and what is the CEO's compensation" abstained entirely.
- Choice: `pipeline/understand.py` splits at strong joints (`;`, a comma plus `and` or `as well as` or `then`, and `and` followed by how, what, whether, which, who, when, where, why) even when the second half names no metric, and at plain commas and `and` only where both sides ask for a metric (so `between FY2023 and FY2024` and metric names such as `earnings before interest, tax, depreciation and amortisation` stay whole). A follow up such as `and how did it grow` is not a topic of its own (the prior period sub-question already answers it). Each sub-question carries the company of the question in parentheses (`how concentrated is its customer base (Aurora)`) and the periods it lacks. `sub_questions` is filled with the pieces, an uncovered piece becomes its own `MissingInfo` and `MISSING` claim, and the answer abstains only when no piece is covered. The lexicon gained `customer base` for the largest customer share.
- Effect on the evaluation: the multi fact queries (headcount and production sites, gross margin and largest customer) are now two sub-questions, so each fact is retrieved and written separately. Against the evaluation run before this change the principal numbers moved by about one to two points (citation recall 0.931 to 0.926, contradiction recall 0.954 to 0.937); the change and the new frozen tau (D82) are mixed in that comparison, so the new `RESULTS.md` is the reference.
- Cost: the mock splitter is rule based; a question with three joints is cut at four sub-questions at most (`MAX_SUB_QUESTIONS`).

## D84. A buyer contradiction names the buyer (core)
- Context: review finding M3. A contradiction on a general layer question was titled "General FY2024 market capitalisation" because the subject was a placeholder when there is no deal.
- Choice: the subject is the deal name inside a deal, else the longest entity the question names (`Tarnix Systems FY2024 market capitalisation`), and the word `static` is dropped from the subject of undated metrics. Test: `tests/integration/test_compound_questions.py`.

## D85. Report fixes from the review (core)
- M1: the abstention section prints the compared score from `adapter_config` (`relevance`) and describes `choose_tau` as the code does (the (m+1)th smallest dev score). M6: the header prints `paraphrase_rate` and `hard_negative_rate` per seed. L1: the latency columns say "wall clock, differs on every run" (the timing markers stay). N3: section 0 shows the end to end false abstention and the abstention precision (abstentions of the full pipeline that were on unanswerable questions). Tests: `tests/unit/test_metrics_report.py`.

## D86. Buyers rank by the proven floor of their score (core-llm)
- Context: review finding 12. `score = met / known` ignores the weight without evidence, so a buyer with one met criterion (1.00 at 12 percent coverage) ranked above a buyer with 0.88 at 47 percent.
- Choice: every card carries `score_low = met weight / applicable weight` (unknown counted as not met) and `score_high = (met + unknown weight) / applicable weight` (unknown counted as met); the rank orders by `score_low`, then score, coverage and id. The card shows the range. Python and TypeScript share the rule through `scoring_vectors.json` (regenerated, the default case now ranks `b_e` before `b_b`).
- Alternative: a combined `score x coverage`, or a Wilson style lower bound. `score_low` is the same product for a fixed weight set, needs no constant and is readable as "weight already proven met".
- Cost: a buyer with little evidence ranks low even when everything known about it is good; the range on the card says why.

## D87. Stage 1 is prefilled from the deal record (core-llm)
- Context: review finding 13. Without typed filters, geography and size were `unknown` although the deal states its region and value; the harness had to inject them (D80).
- Choice: `Deal` gains optional `geographies`, `ev_eur_m`, `buyer_types`. An empty filter is filled from them (`prefill_from_deal`), size as `ev x min_size_multiple_of_ev` to `ev x max_size_multiple_of_ev` (1 and 60, `ScreeningParams`, parameters not sources), and the rationale says "from the deal record". A typed filter wins. The generator writes the Aurora region and EV; the harness now screens with no typed filter, the product path. Buyer type stays `unknown` when the deal states no preference.
- Alternative: keep the filters manual. Rejected: the deal already knows the answer.
- Cost: three optional contract fields; deals other than Aurora state none, so their stage 1 is unchanged.

## D88. Live calls: structured output, no silent mock, a separate judge (core-llm)
- Context: review findings 6 to 9. A live failure was answered by the mock with only a suffix on `Trace.provider`; Gemini read its schema from the prompt; retries ignored `Retry-After`; the judge was the writer model.
- Choice: Gemini receives `generationConfig.responseSchema` (the pydantic schema converted to the OpenAPI subset: `$ref` inlined, `anyOf null` as `nullable`). Retries honour `Retry-After` (seconds or HTTP date, capped at 60 s) and fall back to exponential backoff; each provider object caps calls in flight (`LLM_MAX_CONCURRENCY`, 4). A failed call raises `LLMError`; the API answers 503 with the reason. `LLM_ALLOW_MOCK_FALLBACK=true` restores the mock fallback, and the answer then carries `degraded=true` and a reason the web client shows in an alert. `JUDGE_PROVIDER` and `JUDGE_MODEL` select the judge; the trace and the report name both models. The API keeps one `RetrievalEngine` per process (review finding 5).
- Alternative: `responseJsonSchema` (full JSON Schema) instead of `responseSchema`; the subset is what the brief asked for and is accepted by every Gemini 2.x model.
- Cost: prices in `prices.json` stay null until the owner copies them from the pricing page, so `cost_usd` is null for live calls; tokens (thinking tokens included) are exact. No live call was made in this work: there was no key in the environment.

## D89. The verifier binds a number to its role, period and column (core-llm)
- Context: review finding 11. `numeric_match` accepts a number found anywhere in the quote, so "largest customer 41.0 percent" passed on a top five share, and "FY2024 adjusted EBITDA 11.2" passed on the FY2022 column.
- Choice: a fourth check, `binding`, between `numeric_match` and the judge. Role: a claim about one entity (`largest customer`) fails on a number whose clause gives it to a group (`top five`), and the reverse. Column: in a table row the header year of the number's column must be a claimed year. Sentence: when the sentence names two years or more, the year nearest to the number (parentheses that do not hold it excluded) must be a claimed year. A source that gives no role or period passes. Tests: `tests/unit/test_verify_binding.py` (both observed errors).
- Alternative: leave binding to the judge. Rejected: the mock judge cannot do it and a live judge was never validated.
- Cost: rules over English phrasings; a binding stated across sentences is not checked.

## D90. Mock and live results live in separate files (core-llm)
- Context: the brief asks for two sections, mock and live, with both models named.
- Choice: `make eval PROVIDER=gemini` writes `RESULTS_LIVE.md` and `latest_live.json`; the mock `RESULTS.md` names writer and judge in its header and ends with section 9, which summarises `latest_live.json` when it exists and otherwise says `live run not executed`. `make live-smoke` runs a few real queries through the pipeline and refuses to run without a key or with the mock fallback on.
- Alternative: one file with both providers. Rejected: a live run is not byte reproducible and must not change the mock file.
- Cost: the live section is only as fresh as the last live run; its date and commit are printed.

## D91. A structured fact base built from the planted facts (factbase)
- Context: brief item C. Everything was text; a keyed value had no record of its own.
- Choice: `ainma.factbase`, built by the generator from `truth/facts.json` (`structured/factbase.json`). Each record keeps a source of record (current document, best tier, most recent) with a verbatim provenance that is a valid `Citation`, and every other current document stating the key. Read through typed request models only (`lookup`, `comparables`, `buyer_facts`); the access predicate is inside each tool. `synth verify` rebuilds and compares it, and checks every provenance against the stored chunks.
- Alternative: a SQLite table in `store/`. Not done to stay out of the store, which another workstream changes; the in-memory base applies the same access rule. A Postgres table can replace it behind the same tools.
- Cost: the base is as good as the planted facts; it adds no fact that no document states. Precedent transactions, broker estimates and news events are not in it yet.

## D92. Keyed sub-questions are routed to the structured base (factbase)
- Context: brief item C, routing between text search and structured lookup.
- Choice: a sub-question naming exactly one metric and at most one period, in a question that does not ask for a change over time, is looked up (`route_request`). When exactly one record answers it in the user's scope, the record becomes a SOURCED claim (`origin="structured"`) citing its provenance, and each disagreeing document a second claim; both go through the same verifier and contradiction stages as text claims, so a disagreement is shown with both sides and no winner. Anything ambiguous (several periods or entities) or anything else stays on text search. `PipelineConfig.structured_routing=False` turns it off; the report measures the product against text only (section 2).
- Alternative: let the LLM choose a tool. Kept for the live path; the rule router is deterministic and testable, and the typed tools are what a model would call.
- Cost: metrics and periods are read by the lexicon (`target_metrics`, `detect_periods`), so routing inherits its coverage; a growth question is never routed so the writer can derive the change.

## D93. A news event layer with its own truth (news)
- Context: the core is to be driven by news; the feed had 60 items, acquisitions and filler, and no truth about events.
- Choice: `synth/news_events.py` appends items from a separate random stream (the base 60 and every earlier truth file are unchanged): duplicated acquisition reports, leadership changes, rumours and their denials, prices and their corrections, with `truth/news_events.json`.
- Alternative: rewrite the feed. Rejected: every earlier number would move for reasons unrelated to the change.
- Cost: wordings are templated; the rule extractor reads them, a live model must generalise. Event wordings avoid the screening's acquisition verbs, so the screening still counts acquisition reports per document and does not deduplicate across outlets; moving screening onto the event layer is the next step.

## D94. Market events are consolidated from cited reports (news)
- Context: a news-driven analyst needs events, not articles: one acquisition reported twice, a rumour later denied, a price later corrected.
- Choice: `ainma.news.market_events` runs the `extract_events` task on each news passage of the deal (mock: headline rules; live: the same request), keeps a draft only when its quote is a verbatim span (citation built by code), then groups reports by (kind, actor, counterparty): duplicates add citations, a denial makes a rumour `denied`, a correction replaces the price and keeps the first figure as `superseded_citations`. `GET /deals/{id}/events` serves them; the harness scores them against the truth (recall, precision, status, corrected value, denied rumours reported otherwise, duplicates merged).
- Alternative: let the writer read raw articles. It cannot tell a denied rumour from a fact.
- Cost: grouping is on exact normalised names; a model that spells a name two ways splits one event in two.

## D95. Model assisted stage 2, rules first, evidence verified by code (screening)
- Context: brief item D3. Stage 2 was rules only; nothing intelligent read the buyer's evidence.
- Choice: with `ScreeningRequest.llm_assist`, a deep criterion that the rules leave `unknown` goes to the `assess_criterion` task with numbered evidence: the buyer's structured facts (provenance quote) and up to six retrieved passages of its documents, plus the deal facts and the documented parameters marked as parameters. The model returns a verdict and, per item it relies on, a verbatim quote; code keeps a citation only when the quote is a span of that item, and a verdict without one verified citation stays `unknown` with a note. A rules verdict is never overridden. The offline mock answers `unknown`, so mock runs are the rules baseline; the report prints `live run not executed` for the assisted mode until a live run measures it next to the rules.
- Alternative: let the model judge every criterion. Rejected: the rules are measured (99.8 percent accuracy where they give a status) and the model is not.
- Cost: one model call per unknown criterion and buyer (up to a few hundred per screening); the model can still be wrong with a true quote that does not decide the criterion, which only a live measurement against the buyer truth can show.

## D96. A committed out of distribution set, read but never tuned on (evaluation)
- Context: the synthetic test split is written by the same author as the system, so A4 and A5 saturate; the brief asks for a set in another vocabulary.
- Choice: `eval/datasets/ood/`: 5 hand written documents of 2 fictional deals (net sales, turnover, FY24, EUR 0.21bn, GM%, FTEs, order book, 31/12/2024, tables with FY22 columns or plain years), 36 questions (30 answerable with value and gold strings, 6 unanswerable). `make eval-ood` writes `eval/results/OOD.md`. Rule: nothing is tuned on it; every look at it is disclosed here.
- First run (mock): Recall@10 1.000 for A1 to A5, MRR 0.961 for A5, answer accuracy 0.567, false abstention 0.400, correct abstention 1.000. Retrieval finds the passages; the frozen `tau`, calibrated on synthetic relevance scores, abstains on 12 of 30 answerable questions. This is a measured negative result, published as is, and no threshold was changed after reading it.
- Cost: 36 questions give wide uncertainty; the documents are short, which favours retrieval. It does not replace real documents.
- Measured regression, fixed (D92 addendum): the first run with routing on (mock, five seeds) gave citation precision 0.668 and recall 0.657 against 0.909 and 0.926 for text only. Two causes, found on seed 1234 test queries: a routed claim cited only the document of record, while the gold fact was the same value in another document (the financial model rather than the CIM), and two metric labels did not match the question vocabulary (`aum`, `plants` written instead of `assets under management`, `production sites`, plus a `count` unit). The routed claim now cites the record and every agreeing document, and labels come from the lexicon. After the fix, all 142 routed claims of the first 120 test queries of seed 1234 cite a gold support chunk. The rerun numbers are in `eval/results/RESULTS.md`.
