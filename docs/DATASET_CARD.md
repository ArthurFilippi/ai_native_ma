# Dataset card: ainma synthetic corpus

All content is synthetic. Every company, fund, person, figure and document is fictional and
generated from a seed. Documents carry the visible mark "SYNTHETIC DOCUMENT, fictional data"
(first body paragraph, and the running header of PDFs); metadata carries `synthetic = true`.
No real bank, client, company or person appears. Names are drawn from syllable lists and may
coincide with real names by accident only.

Generate and verify:

```
python -m ainma.synth generate --seed 1234 --out data/synthetic
python -m ainma.synth verify data/synthetic/1234
```

One seed takes about 3 seconds to generate and under 2 seconds to load and verify. The same seed
gives byte identical files (tested by hashing every output twice). Only
`data/synthetic/1234/truth/` is committed (decision D07); everything else is regenerated.

## Construction

Three layers, all derived from one structured "world" (companies, buyers, acquisitions):

| Layer | Content (seed 1234) |
|---|---|
| General knowledge, `deal_id = null`, `internal_reference` | 30 documents: process playbooks, NDA and SPA templates, 12 precedent memos, 8 sector guides |
| Deal data rooms | 9 deals. `deal_aurora` (demo deal, 14 documents: CIM PDF of 24 pages, management presentation DOCX, financial model XLSX with P&L, balance sheet and cash flow for FY2020 to FY2024, signed NDA, draft SPA (superseded) and executed SPA, board minutes, quality of earnings summary, customer concentration note, press release (withdrawn) and its correction, two trade press articles, one old article). 8 further deals (`deal_borealis`, `deal_cygnus`, `deal_draco`, `deal_eridanus`, `deal_fornax`, `deal_gemini`, `deal_hydra`, `deal_lyra`) with 6 to 8 documents each. Memberships: `u_lead` is lead of every deal, `u_analyst` is a member of `deal_aurora`, `u_outsider` has none |
| Market and buyers, `deal_id = null`, `entity_id = buyer id` | 40 buyers (20 strategic, 20 financial), 3 to 5 documents each (179 in total): profile page (`web`), annual report excerpt or fund summary (`company_report`), acquisition press releases, trade articles, some old press releases and annual filings (`regulatory_filing`). Plus 60 dated simulated news items in `news/items.json` |

Facts are planted as sentences or table rows. Each metric has several literal phrasings,
paraphrases that avoid the canonical words, a footnote form and a table row form. A fact has
one primary span (the first occurrence) and every other occurrence in the same document is
recorded in `truth/aux.json`. `support_chunk_ids` lists every stored chunk containing an occurrence.
The spans are located in the text parsed back from the written file, never computed from the
generator's own layout.

### Parameters (recorded in `truth/params.json`)

| Parameter | Value | Effect |
|---|---|---|
| `paraphrase_rate` | 0.35 | share of planted facts phrased with a paraphrase, and of queries asked in paraphrased words |
| `hard_negative_rate` | 0.30 | per deal: a trade article that mentions a similarly named company with its own figures, and a restated prior-year revenue in the management presentation (a planted contradiction) |
| reference date | 2025-06-30 | "today" for the freshness windows (press 180 days, deal documents 540 days, filings 730 days); encoded in `generator_version` and in `aux.json` |

Hard negatives are also near-miss numbers in other periods (every financial sentence and table
carries neighbouring years), the adjusted EBITDA next to EBITDA, and a draft SPA next to the
executed one. Lowering the rates makes the set easier and must be reported with the results.

### Ground truth files

`manifest.json`, `news/items.json`, `truth/{deals,users,buyers,facts,queries,unanswerable,contradictions,stale,kpi_truth,buyer_truth,judge_labels,params}.json`
as in `ainma/truth.py`, plus the sidecar `truth/aux.json`. Query splits (dev 30 percent, test 70 percent) are
`ainma.truth.split_of(query_id)`, judge labels use it on the label id.

- **Queries**: single fact, paraphrased, hard negative, multi fact and comparison. Relevance is 2 for the chunks
  containing a gold fact and 1 for chunks of other current facts with the same key (corroboration).
  A contradiction query lists every fact of the key as gold.
- **Unanswerable**: 12 deal topics (CEO compensation, FY2026 revenue guidance, FY2027 EBITDA forecast, lawsuits, pensions,
  patents, attrition, environmental liabilities, credit rating, insurance, churn, dividends) rotated over the 9 deals,
  6 general topics and 6 buyer topics. `hard` marks the ones that reuse corpus vocabulary (a period or a topic word
  that exists, with an unseen qualifier). `verify` checks that none of the topic's terms occurs in any chunk of the question's scope.
- **Contradictions** (`contradictions.json`): kinds `contradiction` (documents of different or equal tiers disagreeing beyond
  0.5 percent on a keyed fact), `consistent_control` (same key restated consistently), `superseded` (draft SPA, replaced by the executed
  SPA) and `withdrawn` (press release replaced by its correction). Superseded and withdrawn documents are excluded from the
  contradiction and control groups. Controls cover every multi-document agreeing key, not only a sample.
  The Aurora demo key is FY2024 revenue: CIM (tier 2) 182.4, financial model (tier 2) 182.4, trade press (tier 4) 179.
- **Stale cases**: facts whose every supporting source is older than its window at the reference date and that have no fresher corroboration
  (old trade articles, prior-year decks, old press releases and filings of buyers). Document types without a window are never stale.
- **Judge labels**: 68 sampled facts, 6 constructed claims each (408 in total): `supported` (faithful), `unsupported` (altered number,
  altered period, altered entity, unrelated claim) and `partial` (true statement joined with an unsupported one).
  A second altered number replaces the altered period for facts without a period. `verify` checks numbers against the chunk text.
- **KPI truth**: 20 KPIs by 5 periods (FY2020 to FY2024) for `deal_aurora`, 100 rows, equal to the cells of the model.
- **Buyer truth**: criteria for Aurora (sector industrial components, region Central Europe), derived from structured fields and re-derived by
  `verify` from the stored buyer documents, facts and news.

### The 20 KPI ids (same ids as the legacy `default_kpis.py`)

Extract: `revenue`, `cogs`, `ebitda`, `ebit`, `net_income`, `operating_cash_flow`, `capex`, `cash`, `total_debt`, `total_assets`, `total_equity`, `interest_expense`.
Compute: `gross_profit` (revenue - cogs), `gross_margin` (gross_profit / revenue * 100), `ebitda_margin`, `net_margin`, `free_cash_flow` (operating_cash_flow - capex),
`net_debt` (total_debt - cash), `leverage` (net_debt / ebitda), `interest_coverage` (ebit / interest_expense).
Units: `EUR m`, `%`, `x`. The model shows each extract KPI as a row. Compute KPIs `gross_profit` is also a model row; margins, free cash flow, net debt, leverage and coverage are not rows, so they must be computed.

### Buyer truth rules (statuses `met`, `not_met`, `unknown`)

| Criterion | Rule |
|---|---|
| `sector_focus` | Aurora sector in the buyer sectors |
| `geography` | Central Europe in the buyer geographies |
| `size_range` | buyer size (market cap or AUM) between 1x and 60x the Aurora enterprise value |
| `regulatory_fdi` | text states state ownership or defense exposure: not_met; states private ownership without state shareholders: met; silent: unknown |
| `recent_activity` | no acquisition evidenced in press releases or news: unknown; an acquisition in the Aurora sector within 36 months: met; otherwise not_met |
| `ticket_fit` (financial) | Aurora equity value / fund size within 5 to 40 percent: met, else not_met (dealbreaker) |
| `fund_lifecycle` (financial) | listed vehicle: met; stated investment period end at least 2 years after the reference year: met, earlier: not_met; unlisted without a stated end: unknown |
| `ev_ratio` (strategic) | Aurora EV / buyer market cap above 60 percent: not_met (dealbreaker), else met |
| `integration_bandwidth` (strategic) | no acquisition evidenced: unknown; at most 2 acquisitions in 24 months: met, more: not_met |
| `antitrust` (strategic) | market share stated: 35 percent or more is not_met, below is met; not stated (and always for financial buyers): unknown |

`buyer_type` is not a truth row (the default request accepts both types). Aurora economics: enterprise value is 8.5 to 10.5 times FY2024 EBITDA,
equity value is enterprise value minus FY2024 net debt (both stated in the CIM, enterprise value also in the executed SPA).

## Sizes per seed

Minimums come from the evaluation plan: 150 answerable, 40 unanswerable, 30 contradictions, 30 controls, 15 stale, 10 superseded and withdrawn, 300 judge claims, 20x5 KPI rows, 40 buyers.

| Seed | Documents | Facts | Answerable queries | Unanswerable | Contradictions | Controls | Superseded + withdrawn | Stale | Judge claims | KPI rows | Buyer truth rows |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1234 | 280 | 663 | 336 | 50 | 48 | 132 | 12 | 32 | 408 | 100 | 320 |
| 1 | 272 | 663 | 331 | 50 | 48 | 131 | 12 | 32 | 408 | 100 | 320 |
| 2 | 269 | 672 | 340 | 50 | 52 | 134 | 12 | 32 | 408 | 100 | 320 |
| 3 | 272 | 661 | 336 | 50 | 50 | 131 | 12 | 32 | 408 | 100 | 320 |
| 4 | 277 | 666 | 334 | 50 | 49 | 134 | 12 | 32 | 408 | 100 | 320 |

Produced by `python -m ainma.synth generate` and checked by `python -m ainma.synth verify` for each of the five seeds.

## Known biases and limits

- **Templated language.** Sentences come from a small set of templates and a combinatorial filler. Retrieval and extraction on this corpus are easier
  than on real documents; absolute scores are optimistic and only differences between systems under identical conditions mean something.
- **Author bias.** The same authors wrote the generator, the truth rules and the system. Phrasing, chunk size, the 5 to 40 percent ticket band
  and the contradiction tolerance leak into both sides.
- **Optimistic recall.** Every gold fact is planted exactly once per document and located verbatim; real corpora contain unplanted relevant passages that
  the relevance judgments would label 0. Support sets contain every occurrence found by construction.
- Filler never contains numbers, so numeric extraction is not confused by incidental figures. Prose uses straight ASCII text, no scans, no OCR, no multi column layout.
- The PDF parser relies on the writer's conventions (fonts, spacing), see D12. Dates, tiers and statuses are exact; real metadata is noisier.
- Deal sectors and company names are fictional and can overlap lexically (similar names are planted on purpose as hard negatives).

## Structured fact base (`structured/factbase.json`)

Built by the generator from the planted facts of the seed (`ainma.factbase.build_factbase`), so
it shares the seed and the ground truth. It is regenerated with the corpus and is not committed.
It plays the role of a data vendor or an internal database: a keyed value with a source of
record, never a value without a passage.

| Field | Meaning |
|---|---|
| `companies[]` | `deal_id`, `name` (the deal's target: the entity of its revenue facts), `sector`, `geographies` |
| `facts[].id` | `sf_00001` ... |
| `facts[].deal_id`, `entity`, `entity_id` | scope (null: general layer), entity name, buyer id when the entity is a buyer |
| `facts[].metric`, `period`, `value`, `unit` | the key (`period` is `FY2024` or `static`) and the value of record |
| `facts[].provenance` | `document_id`, `doc_title`, `doc_type`, `tier`, `published_on`, `status`, `chunk_id`, `page`, `char_start`, `char_end` (page offsets, as a citation), `quote` (verbatim) |
| `facts[].others[]` | every other current document stating the same key, with its value and provenance |

Source of record: current documents only (superseded and withdrawn are never a source), best
tier first, then the most recent, then the lowest document id. A value of `others` that differs
by more than 0.5 percent is a disagreement; the question pipeline shows it as a contradiction
with both sides cited.

Seed 1234: 430 records, 651 provenances, 48 records with a disagreeing document (the 48 planted
contradictions), 9 companies. `python -m ainma.synth verify` rebuilds the file from
`truth/facts.json` and requires equality, and checks every provenance against the stored chunk
(the quote is in the chunk, the page offsets point at it).

Typed tools (`ainma.factbase.FactBase`), the only way to read it: `lookup(LookupRequest(metric,
entity, period))`, `comparables(ComparablesRequest(metric, period, sector))`,
`buyer_facts(BuyerFilterRequest(metric, min_value, max_value, buyer_ids))`. Requests are strict
models (an unknown field is rejected); no query text is ever written by a model. The access
predicate (the user's deals, or the general layer) is applied inside each tool before matching.

Not yet in the base: precedent transactions with acquirer and date, broker estimates, earnings
call statements, and news events. They come with the next corpus extension.
