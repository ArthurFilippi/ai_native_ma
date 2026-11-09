"""Hybrid retrieval: BM25, dense (LSA by default), RRF, reranker, source ranker."""

from ainma.contracts import AccessContext
from ainma.retrieval.config import RankerConfig, RerankerWeights, RetrievalConfig, System
from ainma.retrieval.engine import RetrievalEngine, SearchHit, SearchResult
from ainma.store.base import Store

__all__ = [
    "RankerConfig",
    "RerankerWeights",
    "RetrievalConfig",
    "RetrievalEngine",
    "SearchHit",
    "SearchResult",
    "System",
    "search",
    "search_detailed",
]


async def search_detailed(
    query: str,
    *,
    store: Store,
    access: AccessContext,
    deal_id: str | None,
    config: RetrievalConfig | None = None,
    engine: RetrievalEngine | None = None,
) -> SearchResult:
    """Like `search`, plus the withdrawn hits, the reference date and the candidate count."""
    return await (engine or RetrievalEngine()).search(
        query, store=store, access=access, deal_id=deal_id, config=config
    )


async def search(
    query: str,
    *,
    store: Store,
    access: AccessContext,
    deal_id: str | None,
    config: RetrievalConfig | None = None,
    engine: RetrievalEngine | None = None,
) -> list[SearchHit]:
    """Ranked passages for `query` among the chunks `access` may see in `deal_id` (plus the
    general layer). Pass one `RetrievalEngine` across calls to reuse the fitted indexes."""
    result = await search_detailed(
        query, store=store, access=access, deal_id=deal_id, config=config, engine=engine
    )
    return result.hits
