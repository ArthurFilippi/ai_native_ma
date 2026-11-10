# Review of the core (retrieval, answer, verifier, judge, screening)

Base reviewed: `main` at `c55a6bd` (tags `phase-a`, `phase-b`, `phase-c`). `make check` was green
on that commit (ruff, `mypy --strict`, 521 tests). Each finding says how it was checked: read in the
code (file and line on `c55a6bd`), or run.

Status words: **confirmed** (checked), **refuted** (checked and false), **not checked**.

## What works

- Citations are built by code (`pipeline/write.py:31` `locate_quote`, `:46` `build_citation`): the
  model returns a passage number and a quote, never offsets. A quote that is not in the chunk
  rejects the evidence. Confirmed by reading.
- Three claim statuses are enforced by the contract (`contracts.py`, `Claim._status_is_consistent`)
  and an abstained answer cannot hold a sourced claim (`Answer._abstention_is_consistent`).
- The access predicate is inside the store query (`store/sqlite.py`, `candidates`); the engine fits
  its indexes on the candidates of one access context only (`retrieval/engine.py:212`).
- Contradictions are objects with sides and no winner (`pipeline/contradictions.py`).
- The evaluation harness is honest about its own limits (stub labels, frozen `tau`, D61 disclosure).
- The human label path exists end to end: `label_sample.py --score` writes `label_scores.json`, and
  `evaluation/run.py:83` `read_hand_labels` feeds it to the report (`report.py:486`). The labels
  are empty, so the report says `not labelled yet`. Confirmed.

## What is fragile

1. **The default reranker is hand written, not learned.** `retrieval/rerank.py:86`
   `FeatureReranker` is a weighted mean of six hand set features (`retrieval/config.py:17`), driven
   by a 490 line lexicon (`retrieval/lexicon.py`) and a regex fact extractor
   (`retrieval/quantities.py`). Confirmed. The A3 to A4 jump (0.720 to 0.927) is this component.
2. **The dense default is LSA** (`retrieval/engine.py:79` `default_embedder`). `fastembed` is wired
   (`FastEmbedEmbedder`, `CrossEncoderReranker` at `rerank.py:184`) but never evaluated. Confirmed.
   The cross encoder path also drops the entity gate (it ignores `document_terms`), so switching to
   it would silently lose D61. Confirmed by reading.
3. **A4 and A5 are near saturation** on data written by the same author as the system (Recall@10
   1.000). They say nothing about real documents. Confirmed from `eval/results/RESULTS.md`.
4. **Synonym robustness rests on finite lexicons.** Confirmed by reading `lexicon.py`; the out of
   distribution test of 4 hand written documents mentioned in the brief is not in the repository,
   so its 8 of 9 result is **not checked** here.
5. **One fitted index per question in the API.** `api/services.py:22` calls `pipeline_ask` without
   an `engine`, so `ask_detailed` builds a throwaway `RetrievalEngine` (`pipeline/ask.py:141`) and
   refits BM25 and LSA on the whole deal for every question. Confirmed.

## What is wrong

6. **A live failure becomes a mock answer.** `llm/providers/__init__.py:32` wraps every live
   provider in `FallbackLLM(..., MockLLM)` and `llm/cache.py:83` returns the mock output on any
   `LLMError`. The only trace is a suffix on `Trace.provider` (`pipeline/ask.py:108`). A user reading
   the answer is not told that a rule based routine wrote it. Confirmed.
7. **Gemini does not use structured output.** `llm/providers/gemini.py:44` pastes the JSON schema
   into the system prompt (`with_schema`) and only sets `responseMimeType`; no `responseSchema`.
   Confirmed.
8. **Retries ignore `Retry-After`** and there is no concurrency limit across calls
   (`llm/providers/http.py:94` sleeps `backoff_s * 2**attempt`; one `httpx.AsyncClient` per call).
   Confirmed.
9. **The judge is the writer model.** `settings.py:18` has one `llm_provider` and one `llm_model`;
   `pipeline/verify.py` calls the same `llm` for `TASK_JUDGE`. Self preference bias cannot be
   avoided, and the README promise to name both models cannot be kept. Confirmed.
10. **The mock judge is a rule** (`llm/providers/mock_tasks.py:265` `_judge_overlap`, number, name
    and word overlap), and the reported kappa 0.888 is against labels built by the generator.
    The live judge prompt has never been checked against human labels. Confirmed.
11. **The verifier does not bind a number to its role, period, entity or column.**
    `pipeline/verify.py:35` says so in its docstring: `numeric_match` accepts a claim when the
    number appears anywhere in the quote. Two errors of that class (largest customer share given
    the top five share; an FY2024 claim read from the FY2022 column) are accepted. The two cases
    of the brief came from hand written documents that are not in the repository; equivalent
    cases are rebuilt as regression tests in this branch. Confirmed by reading; in the committed
    evaluation runs the verifier dropped 0 claims (README, "The verifier removed nothing").
12. **Screening ranks a thin score above a broad one.** `screening/scoring.py:81` `_order_key`
    sorts by `score = met / known` first and coverage only breaks ties, so a buyer with one met
    criterion (score 1.00, coverage 0.12) ranks above a buyer with score 0.88 at coverage 0.47.
    Confirmed by reading and by a unit test written before the fix.
13. **Stage 1 stays unknown although the deal knows the answer.** `screening/prefilter.py:68`,
    `:97`, `:101` return `unknown` for buyer type, geography and size when no filter is typed, and
    `Deal` (`contracts.py:156`) has no geography or value range to prefill them. Confirmed.
14. **Stage 2 has no LLM.** `screening/deep.py` is one rule per criterion over retrieved text
    (no `llm` call in the module). Confirmed.
15. **The buyer universe is global** (`store/base.py:59` `list_buyers`), not attached to a deal.
    Confirmed. Antitrust needs a target market share that no document states, so it is `unknown`
    by construction (D75). Confirmed.

## Plan for this branch (`core/llm-search`)

Ordered by what makes a visible claim wrong or a failure silent, then by product value:
A (LLM layer: structured output, `Retry-After`, concurrency, separate judge model, no silent
fallback), the screening ranking and prefill (findings 12, 13), the verifier binding check
(finding 11), the shared engine (finding 5), then the evaluation report (mock and live sections,
writer and judge named). The outcome of each item is recorded at the end of this file.

## Outcome of this branch

All numbers below come from `eval/results/RESULTS.md` (mock provider, five seeds, test split),
regenerated on this branch. "Before" is the committed report of `c55a6bd`.

### Fixed

| Finding | Fix | Evidence |
|---|---|---|
| 5 refit per question | `Runtime.engine`, one `RetrievalEngine` per process | `tests/integration/test_api_llm.py`: two questions, one fit |
| 6 silent mock answer | `LLMError` gives 503; mock only with `LLM_ALLOW_MOCK_FALLBACK`, answer `degraded` and shown | `test_llm_live_layer.py`, `test_pipeline_judge_degraded.py`, `web/tests/degraded.test.tsx` |
| 7 schema in the prompt | `responseSchema` (OpenAPI subset) | `test_gemini_sends_response_schema_not_a_schema_in_the_prompt` |
| 8 retries | `Retry-After` honoured and capped, concurrency gate per provider | `test_retry_after_*`, `test_concurrency_is_limited_per_provider` |
| 9 judge is the writer | `JUDGE_PROVIDER`, `JUDGE_MODEL`; trace and report name both | `test_judge_calls_go_to_the_judge_model_and_the_trace_names_both`, report header |
| 11 number binding | `binding` check (role, column, sentence period) | `tests/unit/test_verify_binding.py` (both observed errors) |
| 12 ranking | rank by `score_low`, range shown on the card | `test_thin_perfect_score_does_not_outrank_broad_good_score`, shared vectors |
| 13 stage 1 unknown | prefill from `Deal.geographies`, `ev_eur_m`, `buyer_types` | `test_stage_one_is_prefilled_from_the_deal_when_no_filter_is_typed` |

Every bug test was written and seen failing before its fix.

### Before and after, mock

| Measure | Before | After |
|---|---|---|
| Citation precision / recall (verifier on) | 0.909 / 0.926 | 0.909 / 0.926 |
| Claims dropped by the verifier | 0 | 0 |
| Correct / false abstention, end to end | 0.920 / 0.082 | 0.920 / 0.082 |
| Screening agreement, unknown rate, false met | 0.702, 47.2%, 0.002 | 0.702, 47.2%, 0.002 |
| Buyer ranking, Spearman vs truth score | 0.528 +/- 0.160 (previous rule, same run) | 0.545 +/- 0.173 |
| Ask latency p50 / p95, harness (shared engine there already) | 42.64 / 227.96 ms | 41.79 / 278.36 ms (other machine) |

Read honestly: on the mock nothing measured improves beyond noise. The binding check removes no
mock claim (the mock writer quotes the right sentence), so its value rests on unit tests until a
live writer is measured. The ranking fix removes a visible inversion but its Spearman gain (0.017)
is far inside the spread across 5 deal runs. Screening agreement is unchanged because the prefill
reproduces the filters the harness used to inject (D80, D87). `tau` was not recalibrated:
retrieval did not change.

### Out of distribution and live

- Out of distribution test set: not built on this branch. The gap between synthetic and out of
  distribution retrieval is **not measured**.
- Live: no `GEMINI_API_KEY` in the environment. `make live-smoke` and section 9 of `RESULTS.md`
  say `live run not executed`. No live number exists.

### What remains (by priority)

1. A live run (`make eval PROVIDER=gemini JUDGE_MODEL=...`, then `make live-smoke`): the only way
   to measure the verifier and the binding check, and the judge against the writer.
2. Hand labels of the 40 pair sample (`make label-sample`, then `--score`): the report already
   reads them; they are not filled, by rule.
3. Brief item B: LLM query understanding (the `understand` task goes to the live model already,
   the prompt is not evaluated), neural dense and cross encoder (code exists; the model host was
   blocked by the network of this run, so nothing was measured; the cross encoder also bypasses
   the entity gate, finding 2), and a committed out of distribution set of 30 to 50 questions.
4. Brief item C: structured fact base with provenance and typed tools. Not started.
5. Brief item D3: LLM assisted stage 2 with verified citations, deterministic rules as baseline.
   Not started; the deep stage is still rules only (finding 14).
6. Brief item E: an adversarial set measured with a live model, verifier on and off.
7. The buyer universe is still global (finding 15); antitrust stays `unknown` by construction.
