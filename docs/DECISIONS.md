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

## D50. API wiring through one guarded module
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
- Choice: the stub ask fills `user_id`, `deal_id` and also `question` from the request, so the question echo on screen is the one asked. It picks the contradiction example when the question contains "revenue" (case-insensitive) and the abstention example otherwise.

## D55. Market intel seed directory
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
