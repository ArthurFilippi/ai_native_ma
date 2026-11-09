# CLAUDE.md

Working conventions for this repository. Read this first, then `_rebuild_dossier/00_CLAUDE_CODE_MASTER_PROMPT.md` if it is present next to the repo (it is not part of the published repo).

## What this repo is

AI-native M&A: a deal-centric platform for a sell-side banking team. Every visible claim is linked to a verbatim source passage, opens in one click, and carries a source reliability tier. The system lights up the decision, it does not take it. Value contract, to be readable in the UI, in outputs and in tests:

> I summarise the evidence clearly and show you the sources, so that you can examine them and make informed decisions.

Scope: sourced question answering, buy-side screening, KPI extraction, honest evaluation. All data is synthetic (labelled `synthetic`) or public. No real bank or client data, ever.

## Commands

```
make install     # pip install -e ".[dev]"
make check       # lint + typecheck + test (must be green before every commit)
make data        # generate the seeded synthetic corpus and ground truth
make eval        # run the evaluation harness, write eval/results/
make api         # run the FastAPI server
make web         # run the web client
make demo        # reproducible five-minute demo (fixed seeds)
```

Targets not yet implemented fail loudly with the phase that delivers them.

## Architecture in ten lines

1. `src/ainma/contracts.py`: pydantic contracts, single source of truth for all exchanged objects.
2. `synth/`: seeded generators for the knowledge base, the fictional data room, buyers, and ground truth.
3. `ingest/`: parsers (PDF, DOCX, XLSX, text) to chunks with page and character offsets.
4. `store/`: `Store` interface (SQLite default, Postgres on Supabase later). Access filter lives inside the query.
5. `retrieval/`: BM25 + dense + RRF fusion + reranker, then the source ranker (tier, recency, corroboration).
6. `pipeline/`: understand, retrieve, write, verify, detect contradictions, abstain. Linear and async.
7. `llm/`: provider interface (`mock`, `gemini`, `openai`) with a disk cache. The mock is deterministic and offline.
8. `screening/`, `kpi/`, `connectors/`: buyer screening (two stages), KPI extraction, market intelligence connectors (simulated).
9. `api/`: FastAPI, demo authentication by header, deal scoping on every route.
10. `web/` and `eval/`: minimal TypeScript client; evaluation harness with datasets, labels, results.

## Conventions

- Python 3.12, fully typed, `mypy --strict` on `src/`, `ruff` for lint and format, async for all I/O.
- No `print` in `src/` (use `logging`). No global mutable state. Seeds are explicit and default to `SEED`.
- Every module ships with tests. A feature is done when its acceptance command passes, not when the code exists.
- Never write a number in the README that did not come from a reproducible `make eval` run.
- Synthetic data is labelled in metadata and visibly in generated documents.
- Secrets live in `.env` only. `.env.example` lists every variable. Never commit a key, a real document or a real name.
- Documentation and comments in English. No em dashes or en dashes in prose; use commas, colons or parentheses.

## Working rules for agents

- Each agent owns a set of paths (listed in its brief) and writes nowhere else. Shared files (`contracts.py`, `pyproject.toml`, `Makefile`, `.env.example`, `CLAUDE.md`) belong to the integration owner.
- Need a change in a shared file? Write a request in `BLOCKERS.md` (gitignored) and continue with a stub. Do not edit another agent's paths.
- Record non-obvious choices in `docs/DECISIONS.md` (one short entry each: context, choice, alternative, cost).
- One branch and one git worktree per agent. Small commits, imperative messages, one concern each.
- Preserve history when moving files (`git mv`). Justify every deletion in the commit message.
- Verify before claiming: run the tests and the acceptance command, read raw outputs, then report.
- Commit messages contain no tool attribution and no co-author trailers.
