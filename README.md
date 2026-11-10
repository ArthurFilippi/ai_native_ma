# AI-native M&A

A deal-centric platform for a sell-side banking team. Every visible claim is linked to a verbatim source passage, opens in one click, and carries a source reliability tier. The system lights up the decision, it does not take it.

> I summarise the evidence clearly and show you the sources, so that you can examine them and make informed decisions.

Scope: sourced question answering over a deal data room, buy-side screening with evidence per criterion, KPI extraction with computed ratios, and an evaluation harness that measures all of it. All data is synthetic (and labelled as such) or public. No real bank or client data is in this repository.

Quick start (offline, no keys, no network after installation):

```
make install     # pip install -e ".[dev]"
make check       # lint, strict typing and the tests
make demo        # generate the seeded corpus, start the API and the web client, print the demo script
make eval        # 5 seeds, mock provider, writes eval/results/RESULTS.md
```

Contents: 1. Context and methods; 2. Repository structure; 3. Data expectations; 4. Modules; 5. Extending the system; provenance note.

---

## 1. Context and methods

### The problem

An analyst preparing a sell-side process reads a data room, press, filings and buyer material, and must be able to say where each statement comes from, how much to trust it, and what is missing. The failure modes that matter are a number without a source, a source that does not say what the answer claims, two sources that disagree while the answer shows only one, and a confident answer to a question the documents do not cover. The design answers each of them with a mechanism that can be tested.

### What the system does

| Mechanism | Behaviour |
|---|---|
| Verified citations | The writer proposes claims with quotes. Code, not the model, locates each quote in the stored chunk and builds the citation (page, character offsets). A claim whose quote is not verbatim, or whose number is not in the quote, is dropped or downgraded. |
| Source reliability | Each document type maps to a tier, T1 (signed agreements, regulatory filings) to T5 (generic web). The tier is shown on every citation, and feeds the source ranker together with recency, status (current, superseded, withdrawn) and corroboration. |
| Contradictions | When two sources disagree on a keyed fact, both sides are shown with their tiers and strengths. The system does not pick a winner. |
| Abstention | When the evidence is below a threshold calibrated on a development split, the answer says that the information was not found and why. |
| Access control | The access predicate is applied inside the store query, before any scoring. A user who is not a member of a deal gets a 404 and no passage of it. |
| Three claim statuses | `sourced` (verified quote), `inferred` (derived, with its inputs shown), `missing` (the information is not in the sources). |
| Screening | Two stages (cheap prefilter, then evidence per criterion for the buyers that pass). A criterion without evidence is `unknown` and is never guessed. One scoring function, mirrored in TypeScript and tested against shared vectors, gives the weighted score and the coverage. |
| KPI extraction | KPI definitions with formulas, a safe `ast` evaluator for computed KPIs, and span verification of every extracted value. |

### Pipeline

`understand` (period, entity, metric) then `retrieve` (BM25 and dense retrieval fused by reciprocal rank fusion, a reranker, then the source ranker) then `write` (claims with quotes) then `verify` (verbatim span, numeric match, judge) then `contradictions` then `abstain`. The pipeline is linear and asynchronous, and every stage records its latency in a trace.

### Methods and the evaluation harness

The target team's rule is adopted as is: you do not improve what you do not measure. Every number below comes from `make eval`, is reproducible from the seeds and a configuration hash, and is printed next to its limits in `eval/results/RESULTS.md`. The harness measures retrieval (nDCG@10, Recall@k, MRR, ablation of five systems A1 to A5), citation precision and recall, the verifier on adversarial claims, abstention, contradiction detection, KPI accuracy, screening agreement, the judge (Cohen's kappa), and latency. Intervals are 95 percent percentile intervals of a paired bootstrap over queries (2000 resamples), with a cluster bootstrap by source document as a sensitivity check and Holm adjustment on the pairwise family. The abstention threshold is chosen on the dev split only (30 percent of query ids, by hash) and reported on the test split (70 percent). Ground truth is emitted by the data generator together with the data, so annotation is by construction.

| Id | System |
|---|---|
| A1 | BM25 |
| A2 | Dense (offline LSA by default) |
| A3 | Hybrid, RRF fusion (k = 60) |
| A4 | A3 plus reranker |
| A5 | A4 plus source ranker (tier, recency, status, corroboration) |

### Results

**These are results of the offline mock baseline, not of an LLM.** The mock provider is deterministic and extractive: it proves that the pipeline, the verifier and the harness work end to end, and it makes the run reproducible byte for byte. It says nothing about the quality of a live model. Live runs (Gemini or OpenAI, configured in `.env`) are reported separately and are not part of these tables. Five seeds, test split, mock provider, dense backend LSA, reranker `features`. Source: `eval/results/RESULTS.md` (run metadata, configuration hash and the full tables are there).

| Principle metric | Value [95% CI] |
|---|---|
| Citation precision (verifier on) | 0.909 [0.892, 0.926] |
| Citation recall (verifier on) | 0.926 [0.912, 0.940] |
| Correct abstention, end to end | 0.920 [0.873, 0.960] |
| False abstention, end to end | 0.082 [0.068, 0.098] |
| Abstention precision (abstentions on unanswerable questions / all abstentions) | 0.585 |
| Contradiction detection recall | 0.937 [0.897, 0.971] |
| Clicks to verify a claim | 1 by design; asserted by a jsdom test of the web client (one citation click, one passage request), not measured in the harness |

Retrieval ablation (nDCG@10, 1188 test queries pooled over the seeds):

| System | nDCG@10 | Recall@10 | MRR |
|---|---|---|---|
| A1 BM25 | 0.744 [0.727, 0.759] | 0.882 [0.866, 0.897] | 0.665 [0.644, 0.685] |
| A2 Dense (LSA) | 0.699 [0.681, 0.716] | 0.867 [0.851, 0.884] | 0.615 [0.594, 0.636] |
| A3 Hybrid RRF | 0.720 [0.703, 0.735] | 0.887 [0.871, 0.902] | 0.632 [0.611, 0.652] |
| A4 plus reranker | 0.927 [0.921, 0.933] | 1.000 [0.999, 1.000] | 0.836 [0.822, 0.850] |
| A5 plus source ranker | 0.960 [0.954, 0.965] | 1.000 [0.999, 1.000] | 0.919 [0.908, 0.929] |

Other measured quantities, same run:

| Quantity | Value |
|---|---|
| Correct abstention on hard unanswerable queries (they share vocabulary with the corpus) | 80.0 percent (n=65); easy ones 100.0 percent (n=85) |
| Contradiction false positive rate (consistent controls, n=472) | 0.000 [0.000, 0.000] |
| Superseded and withdrawn cases (n=42): flagged / cited without the flag / not surfaced | 34 / 4 / 4 |
| Stale-only cases (n=125) flagged as stale or missing | 89.6 percent |
| Verifier recall of not fully supported claims (adversarial, n=1400) | 0.934 [0.920, 0.948] |
| Verifier recall on altered entities | 68.3 percent |
| Judge Cohen's kappa against the constructed labels | 0.888 [0.863, 0.912] |
| KPI accuracy within 0.5 percent (n=500 truth cells) | 0.994 [0.986, 1.000] |
| KPI wrong-value rate (the dangerous error) | 0.006 [0.000, 0.014] |
| Screening agreement with the buyer truth (n=1600 cells) | 0.702 [0.679, 0.724] |
| Screening unknown rate | 47.2 percent |
| Screening, predicted met although not met | 0.002 [0.000, 0.005] |
| Ask, total latency p50 / p95 (wall clock, differs on every run; warm, in memory store, one machine) | 42.64 ms / 227.96 ms |

### How to read these numbers

- **Synthetic and templated data.** Absolute scores are optimistic and say little about real documents. Only differences between systems under identical conditions are informative. The same author wrote the generator and the system, so design assumptions can leak into both. The retrieval figures of A4 and A5 are close to saturated for that reason.
- **The verifier removed nothing in this run.** With the mock writer, which builds claims from verbatim quotes, citation precision, recall and the unsupported-claim rate are identical with the verifier on and off, and it dropped 0 claims. The ablation is wired and reported, but the mock cannot show what the verifier is worth. A live model is needed for that.
- **Citation precision is below one by design choice.** The system surfaces a second, flagged source (a superseded draft, a press figure), and those claims are not gold facts, so they count against precision.
- **Screening agreement is conditional and capped.** The harness screens the way the demo does: the deal's region and size range as filters, every buyer that passes stage 1 reaches stage 2, and the simulated news feed is filed in the deal space first (decision D80). Two limits remain and were not tuned away: the buyer truth for antitrust assumes a target market share that no document states, so a system that does not guess leaves it `unknown`; and the deep truth also covers buyers that fail the sector prefilter, which the product does not deep-screen. This is why the unknown rate is high while accuracy where a status was given is 99.8 percent.
- **Known weak spots.** A chunk-local judge cannot see a wrong company when the chunk names none (tables, "the company"), hence the altered-entity recall above; the pipeline avoids that case upstream with an entity gate. Hard unanswerable questions are abstained correctly less often than easy ones, and abstention precision is 0.585 at the frozen threshold: about four abstentions in ten are on answerable questions. The threshold curve in `RESULTS.md` shows the tradeoff, and the dev false abstention at the frozen `tau` ranges from 5.1 to 14.1 percent across seeds. `tau` must be recomputed by hand whenever retrieval changes.
- **What was tuned on what.** Thresholds and retrieval constants were tuned on the dev split and on seeds 1 and 2; the reported numbers are on the test split of all five seeds. One bug (a stemmed company descriptor in the brand logic) was found after reading the failure categories of one seed on the test split, fixed generally with a regression test, and disclosed in `docs/DECISIONS.md` (D61). The metric glossary was written after reading the generator's phrasings, so the mock numbers are optimistic.
- **Not evaluated.** Live LLM providers, neural embedders and cross-encoders, real documents, production traffic, any user study. The hand-labelled sample that validates the constructed judge labels is generated by `make label-sample` and is not labelled yet, so the report says `not labelled yet` there.

### Deferred and not implemented

Deferred, by decision: the bidder log agent, PPTX and e-mail parsers, scheduled production jobs, paid market data connectors (Crunchbase, Mergermarket, PitchBook), real authentication (the API uses a demo header, see below), import of the Stanford dashboard design, valuation modules from the earlier generation. Optional work not done: a Postgres adapter and hosting (the store is SQLite, the runtime is local), a SEC EDGAR public documents layer, and the routing experiment between a cheap and a strong model. None of these is described as a feature anywhere else in this repository. The market intelligence connector is simulated: it reads a dated news feed that the data generator writes, and fetches nothing from the network.

---

## 2. Repository structure

```
src/ainma/
  contracts.py      pydantic contracts, single source of truth for every exchanged object
  settings.py       settings read from the environment (.env.example lists every variable)
  runtime.py        store, LLM and settings assembled for the API and the CLIs
  truth.py          schemas of the ground truth files
  synth/            seeded generators: knowledge base, fictional data room, buyers, ground truth
  ingest/           parsers (PDF, DOCX, XLSX, text) to chunks with page and character offsets
  store/            Store interface, SQLite implementation, access filter inside the query
  retrieval/        BM25, dense (LSA), fusion, reranker, entity gate, source ranker
  pipeline/         understand, write, verify, contradictions, abstain, ask, trace inspection
  judge/            support judge, daily replay, regression cases
  llm/              provider interface, mock, disk cache, fallback, Gemini and OpenAI providers
  screening/        two stage buyer screening, criteria, evidence, one shared scoring function
  kpi/              KPI definitions, formula evaluator, extraction, scoping
  connectors/       connector interface, simulated news connector, ingestion
  evaluation/       harness, metrics, statistics, report writer, adapter, label sample
  api/              FastAPI application, demo authentication, examples for the schema
  demo.py           data preparation and the five minute demo script
web/                Next.js client (TypeScript strict, plain CSS), evidence panel first
eval/               results, labels (hand labelling sample), regression cases, datasets note
data/synthetic/     generated corpora; only the ground truth of seed 1234 is committed
docs/               DECISIONS.md (every non obvious choice), INTERFACES.md, DATASET_CARD.md
tests/              unit and integration tests, fixtures
scripts/demo.sh     the demo launcher
```

Commands:

| Command | What it does |
|---|---|
| `make install` | install the package and the development tools |
| `make check` | ruff, `mypy --strict` on `src/`, and the tests; must be green before a commit |
| `make data` | generate and verify the corpus of one seed (default 1234) |
| `make eval` | generate the five seeds, run the harness, write `eval/results/` (`PROVIDER` and `SEEDS` are options) |
| `make label-sample` | write the 40 pair blind labelling sheet for the hand labels |
| `make judge-daily` | replay the answer log through the judge |
| `make inspect ID=<answer id>` | print the raw trace of a logged answer |
| `make api` / `make web` | run the API on port 8000 / the web client |
| `make demo` | prepare the data, run API and web client, print the demo script |

The web client has its own checks: `cd web && npm ci && npm run build && npm run lint && npm test`.

---

## 3. Data expectations

**Everything is synthetic.** Every company, fund, person, figure and document is fictional and generated from a seed. Documents carry the visible mark "SYNTHETIC DOCUMENT, fictional data" and their metadata carries `synthetic = true`. Names are drawn from syllable lists and can coincide with real names by accident only. The dataset card, `docs/DATASET_CARD.md`, gives the construction, the parameters, the sizes and the ground truth files.

Three layers, all derived from one structured world:

| Layer | Content |
|---|---|
| General knowledge (`deal_id` is null, internal reference) | process playbooks, NDA and SPA templates, precedent memos, sector guides |
| Deal data rooms | one demo deal, Project Aurora (CIM PDF, management presentation DOCX, financial model XLSX, NDA, draft and executed SPA, board minutes, quality of earnings summary, press material, trade articles), plus further deals with smaller rooms. Memberships: `u_lead` leads every deal, `u_analyst` is a member of Aurora, `u_outsider` has none |
| Market and buyers (`deal_id` is null, `entity_id` is a buyer id) | strategic and financial buyers with profile pages, annual reports or fund summaries, press releases and trade articles, plus a dated simulated news feed |

Facts are planted as sentences or table rows with several phrasings, paraphrases and near misses. Hard negatives include a similarly named company with its own figures, a restated prior year figure (a planted contradiction), a draft SPA next to the executed one, and a withdrawn press release next to its correction. The parameters (`paraphrase_rate`, `hard_negative_rate`) are recorded in `truth/params.json` and printed with the results; lowering them makes the set easier and must be reported.

The generator is seeded and byte deterministic (tested by hashing every output twice). `python -m ainma.synth verify data/synthetic/<seed>` re-derives every ground truth span from the stored chunks. The evaluation uses five seeds (1234, 1, 2, 3, 4) and reports the mean, the standard deviation and the per seed tables. Only `data/synthetic/1234/truth/` is committed, the rest is regenerated by `make data`.

**Public layer.** The design allows a layer of public documents (for example filings). It is not implemented; the corpus contains no public document, and nothing in the repository was downloaded.

**What a real deployment would need to supply.** Documents in PDF, DOCX, XLSX or text with a deal identifier, a document type (which gives the tier), a publication date and a status (current, superseded, withdrawn); a user and membership table; for screening, a buyer universe with structured fields. Real data would also need real authentication, which is deferred.

---

## 4. Modules

**Contracts (`contracts.py`).** `Document`, `Chunk` (with page and character offsets, the invariant being that the chunk text equals the page slice), `Citation`, `Claim`, `Contradiction`, `Answer` (with `value_contract` and a `Trace`), `BuyerCard`, `ScreeningResult`, `KpiValue`. The model of record is this file; the API, the web types and the tests derive from it.

**Store (`store/`).** SQLite by default, no infrastructure. The access predicate (`deal_id` in the user's deals, or the general layer) is part of the SQL that selects candidates, so scoring never sees a forbidden chunk. A property test checks zero leakage across users.

**Ingestion (`ingest/`).** Parsers for PDF, DOCX, XLSX and text produce chunks with page and offsets; `load_corpus(store, seed_dir)` loads a generated corpus with its deals, users, memberships and buyers. PPTX and e-mail parsers are deferred.

**Retrieval (`retrieval/`).** An in-house BM25, an LSA dense embedder (an optional `fastembed` backend exists behind a setting and was not evaluated here), reciprocal rank fusion, a feature based reranker with an entity gate (a question about one company does not retrieve another company's figures), and the source ranker (tier prior, recency half-life, status, corroboration). Systems A1 to A5 are selectable by configuration.

**Pipeline (`pipeline/`).** `ask(question, store, access, deal_id, llm, config)` returns a validated `Answer`. `verify.py` holds the pure checks (`verbatim_span`, `numeric_match`). A compound question is split into sub-questions: each is answered with citations or listed as missing, so an answerable half is never hidden by an unanswerable one. Abstention compares the best passage score with one frozen `tau` (`DEFAULT_TAU`, chosen once on the pooled dev queries of the five seeds, used by the API, the demo and the test split; `python -m ainma.evaluation.run --calibrate-tau --seeds 5` recomputes it, and the report header shows any drift). Answers are appended to a log that `make inspect` and `make judge-daily` read.

**LLM layer (`llm/`).** A provider interface with `mock` (deterministic, offline), `gemini` and `openai` (HTTP, tested on recorded fixtures only, never against a live service in the tests), a disk cache, and a fallback that is never silent (the usage record says which provider failed). Structured outputs are validated with one retry. Citations are built by code from verbatim quotes, so a model cannot fabricate a quote. To use Gemini, set `LLM_PROVIDER=gemini`, `LLM_MODEL` and `GEMINI_API_KEY` in `.env` (never commit that file).

**Judge (`judge/`).** Labels a (claim, passage) pair `supported`, `partial` or `unsupported`; `make judge-daily` replays logged answers, and confirmed failures become regression cases that every `make eval` replays. No regression case is committed yet.

**Screening (`screening/`).** Stage 1 prefilters on buyer type, sector, geography and size. Stage 2 evaluates deep criteria with evidence from the buyer's own documents: ticket fit (financial buyers), EV ratio and integration bandwidth (strategic buyers), fund lifecycle, recent activity, antitrust and FDI. Every number the deep stage assumes (the EBITDA multiple, the equity share, the reference date) lives in one documented parameter object and none of them comes from a source. A criterion without evidence is `unknown`; some criteria are dealbreakers. Weights are adjustable and the ranking is recomputed by the same function in Python and in TypeScript. The score is computed over the criteria that have evidence, so a score of 1.00 can rest on well under all of the weight: read it together with the coverage shown on the card.

**KPIs (`kpi/`).** KPI definitions with formulas, a safe evaluator over the Python `ast` (no `eval`), extraction from the deal's own documents only, and an adjusted measure is never read as the plain KPI. Computed values show their inputs.

**Connectors (`connectors/`).** A `Connector` interface and a simulated news connector that files dated items into a deal space, so market news feeds the screening evidence. No network access.

**API (`api/`).** FastAPI. Authentication is a demo header, `X-User-Id` (`DEMO_AUTH`), and is not production authentication. Every `/deals/{id}` route checks membership and answers 404 to a non-member. A `viewer` can read documents, ask and open passages, but gets 403 on screening and on the market intelligence run (decision D81). Membership management is not implemented: memberships come from the data loader.

| Route | Purpose |
|---|---|
| `GET /health`, `GET /users` | liveness, demo users |
| `GET /deals`, `GET /deals/{id}`, `GET /deals/{id}/documents` | the user's deals and documents |
| `POST /deals/{id}/ask` | a sourced answer |
| `GET /passages/{chunk_id}` | the passage with highlight offsets, access checked |
| `POST /deals/{id}/screening` | two stage screening with cards |
| `GET /deals/{id}/kpis` | KPI values |
| `POST /deals/{id}/market-intel/run` | file the simulated news feed in the deal |

**Web client (`web/`).** The checks run in CI (build, lint, vitest); an optional real browser script is `web/e2e/one-click.mjs` (Playwright is not a dependency). Next.js, TypeScript strict, plain CSS, no UI library. The structured answer is on the left and the evidence panel on the right: one click on a citation opens the passage with the cited span marked, with the tier chip and the date. Contradiction and abstention have their own states, and the answer screen carries the value contract. Tabs: Ask, Documents, Screening, KPIs, Market. Without `NEXT_PUBLIC_API_URL` it runs on example payloads and a badge says `mock data`.

**Evaluation (`evaluation/`).** One adapter module is the only place that imports `search`, `ask`, `run_screening` and `extract_kpis`; when a component is missing, the harness uses a labelled stub and the report header says `stub` instead of `real`. Every metric has a unit test on a small hand-computed example. The report prints the static limitations paragraph with every table.

---

## 5. Extending the system

**Add your own documents.** Parse them with a parser from `ingest/` into a `Document` (id, deal id, type, publication date, status) and its chunks, and write them with `store.put_document` and `store.put_chunks`. The document type decides the tier through `TIER_BY_DOCTYPE` in `contracts.py`; add a type there and a row to the tier map. Grant access through deal memberships, never by filtering in the caller.

**Add a data generator rule.** Facts and their phrasings are in `synth/`; the generator writes the ground truth together with the documents, so a new fact type needs a phrasing, a truth row and, for queries, relevance judgments. Run `python -m ainma.synth verify` after every change; it re-derives each span from the stored chunks.

**Add a retrieval or ranking method.** Implement it behind the same interface as the existing components, register it as a system in `RetrievalConfig`, and add it to the ablation in `evaluation/`. The harness then reports it with paired intervals against the others. A new ranking feature must show its effect on the citation and contradiction metrics, not on nDCG alone.

**Add a screening criterion.** Add a row to the criteria table in `screening/criteria.py` (key, label, stage, weight, dealbreaker, buyer type), implement its evidence in `screening/deep.py`, and add a vector to `tests/fixtures/scoring_vectors.json` if the scoring rule changes (both the Python and the TypeScript functions must reproduce it).

**Add a KPI.** Add a definition (name, aliases, formula or extraction pattern) to `kpi/definitions.py`; computed KPIs use the safe formula evaluator over other KPIs. Add the row to the KPI truth if you want it measured.

**Add a connector.** Implement the `Connector` interface in `connectors/`, return dated items, and let `run_market_intel` file them. A real fetcher must respect robots rules and terms of use and identify itself; the simulated one does not fetch anything.

**Add an LLM provider.** Subclass the raw JSON provider (implement `_raw`), register it in `llm/providers/__init__.py`, record a fixture of its responses, and test on the fixture only. Report live numbers separately from the mock numbers, naming the writer and the judge model.

**Record decisions.** Every non obvious choice goes in `docs/DECISIONS.md` as one short entry: context, choice, alternative, cost. Conventions are in `CLAUDE.md`.

---

## Provenance

This project was regenerated from an earlier codebase, an aborted startup experiment on AI for M&A workflows (October 2025 to May 2026). The spirit, the central tools and the ideas are preserved: deal-centric workspaces, hybrid retrieval, a unified source object behind every claim, KPI definitions with formulas, buyer screening rules. Part of the architecture was rebuilt by hand and with AI assistance: the verification pipeline, the access model, the data generators and the evaluation harness are new. No data from the original project is included; all documents here are synthetic or public and are labelled as such.
