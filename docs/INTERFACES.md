# Cross-module entry points

These signatures are the integration surface between the phase B agents. Code against them, use a
local stub (a `Protocol` in your own package) until the real module is merged. Names are exact:
the evaluation adapter and the API call them by name.

All functions are `async`, take keyword arguments after the first, never read global state, and
receive the store, the access context and the LLM explicitly.

## Data (`ainma.ingest`, `ainma.synth`)
```python
# ainma/ingest/loader.py
async def load_corpus(store: Store, seed_dir: Path) -> LoadReport
#   reads manifest.json, parses each file, put_document + put_chunks, loads deals, users,
#   memberships from truth/. LoadReport(documents:int, chunks:int)
```
CLI: `python -m ainma.synth generate --seed 1234 --out data/synthetic`,
`python -m ainma.synth verify data/synthetic/1234`. Schemas of every file: `ainma/truth.py`.

## Retrieval and pipeline (`ainma.retrieval`, `ainma.pipeline`) owned by core
```python
class RetrievalConfig(BaseModel):   # system "A1".."A5", rrf_k=60, rerank_top=30, top_k=10, ranker constants
class SearchHit(BaseModel):         # chunk: Chunk, passage: RankedPassage, document: DocumentMeta

async def search(query: str, *, store: Store, access: AccessContext, deal_id: str | None,
                 config: RetrievalConfig | None = None) -> list[SearchHit]

class PipelineConfig(BaseModel):    # retrieval: RetrievalConfig, verifier: bool=True, tau: float, drop_unverified: bool

async def ask(question: str, *, store: Store, access: AccessContext, deal_id: str | None,
              llm: LLM, config: PipelineConfig | None = None) -> Answer

# ainma/pipeline/verify.py (pure functions, no I/O)
def verbatim_span(quote: str, chunk_text: str) -> bool
def numeric_match(claim_text: str, quote: str) -> tuple[bool, str]      # (passed, detail)
```
Answers are appended to `data/cache/answers.jsonl` (id, question, Answer JSON).

## Screening, KPI, connectors (`ainma.screening`, `ainma.kpi`, `ainma.connectors`) owned by biz
```python
# ainma/screening/scoring.py: the ONE scoring function, mirrored in TypeScript
def score_cards(criteria: Sequence[Criterion], cards: Sequence[BuyerCard],
                weights: Mapping[str, float]) -> list[BuyerCard]   # fills score, coverage,
                                                                    # contributions, dealbreakers, rank
async def run_screening(request: ScreeningRequest, *, store: Store, access: AccessContext,
                        llm: LLM) -> ScreeningResult

# ainma/kpi/__init__.py
async def extract_kpis(deal_id: str, *, store: Store, access: AccessContext, llm: LLM,
                       periods: Sequence[str] | None = None) -> list[KpiValue]

# ainma/connectors/run.py
async def run_market_intel(deal_id: str, *, store: Store, access: AccessContext,
                           seed_dir: Path) -> int            # number of documents ingested
```
Shared vectors for the scoring function: `tests/fixtures/scoring_vectors.json`. The Python function
and the TypeScript function must both reproduce them within 1e-6 (rules are written in the file).
Mock mode KPI parsing is a regex routine inside `kpi/`; it does not go through the LLM mock.

## LLM
`ainma.llm`: `LLM`, `Usage`, `MockLLM`, `CachedLLM`, `FallbackLLM`, `RawJsonLLM` (subclass it for a live
provider: implement `_raw`), `build_llm(settings)`, task names in `ainma/llm/tasks.py`. The core
registers mock routines in `ainma/llm/providers/mock_tasks.py::default_mock_handlers`.
Citations are built by code from verbatim quotes. The model never emits offsets.

## Evaluation (`ainma.evaluation`) owned by eval
`python -m ainma.evaluation.run --provider mock --seeds 5 [--smoke]` writes
`eval/results/RESULTS.md` and `latest.json`. One adapter module,
`ainma/evaluation/adapter.py`, is the only place that imports `search`, `ask`, `run_screening`,
`extract_kpis`; until they exist it returns deterministic stubs and says `stub` in the report.

## API (`ainma.api`) owned by app
FastAPI app object `ainma.api.app:create_app(runtime: Runtime) -> FastAPI`; routes in
`02_TARGET_SPEC.md` section 14 (outside the repo, see the brief). Demo auth by `X-User-Id`.
Until core and biz merge, routes serve the payloads of `tests/fixtures/` behind the same
response models.

## Shared helpers already on main
`ainma.settings.get_settings`, `ainma.runtime.open_runtime`, `ainma.store.SqliteStore` (`open(path)`),
`ainma.truth` (file schemas, `split_of`), fixtures in `tests/fixtures/` (`tiny.py`, payload JSONs),
`tests/conftest.py` (`tiny_store`, `load_payload`).
