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
