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

## D40. Scoring edge rules (biz)
- Context: `scoring_vectors.json` fixes the formula, not three edge cases: cards that failed stage 1, criteria that do not apply to a buyer type, ties after float arithmetic.
- Choice: a card with `stage1_passed=false` is unscored (score `None`, coverage 0, empty contributions, no dealbreakers, rank `None`) and listed after the ranked cards. A criterion without a result on a card does not apply: its weight leaves both sums, so a strategic buyer is not penalised for having no `ticket_fit`. `contributions` has a key for every criterion (0.0 when unknown, not met or not applicable). Scores and coverage are compared after rounding to 9 decimals when ranking. Dealbreakers keep their flag when their weight is overridden to zero. Hand-computed vectors for these rules are in `tests/fixtures_biz/scoring_vectors_extra.json`; the TypeScript twin must follow them.
- Alternative: score failed cards on their prefilter results only. Rejected: a score built from prefilter criteria alone reads as a verdict.
- Cost: the twin carries three rules the shared vector file does not test.

## D41. Where the buyer universe comes from (biz)
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
- Choice: 30 definitions kept from the legacy 62 (income statement, cash flow, balance sheet, returns, headcount, customer concentration), same ids, formulas and `depends_on`. Units are `EUR m`, `%`, `x`, `count`; all KPIs are annual with periods `FY2020` to `FY2024` by default. To prune to the 20 KPIs of `kpi_truth.json` after the `data` merge.
