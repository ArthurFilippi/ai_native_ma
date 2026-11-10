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
