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
