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
