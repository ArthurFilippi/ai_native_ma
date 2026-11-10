"""Search over the candidate set of one access context.

The store applies the access predicate and returns the candidates; the BM25 index and the dense
index are fitted on those chunks only and cached by a fingerprint of the candidate set, so a run
of hundreds of queries pays for each fit once. The cache lives on a `RetrievalEngine` object,
never in module state; `search` without an engine builds a throwaway one.
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from collections.abc import Callable, Sequence
from datetime import date

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict

from ainma.contracts import (
    AccessContext,
    Chunk,
    DocStatus,
    DocType,
    DocumentMeta,
    RankedPassage,
    Strict,
)
from ainma.retrieval.bm25 import BM25Index
from ainma.retrieval.config import RetrievalConfig
from ainma.retrieval.embedder import Embedder, FastEmbedEmbedder, LsaEmbedder
from ainma.retrieval.fusion import rrf_ceiling, rrf_fuse
from ainma.retrieval.quantities import ExtractedFact, extract_facts_rules
from ainma.retrieval.ranker import (
    chunk_recency,
    corroboration_bonus,
    corroboration_count,
    final_score,
)
from ainma.retrieval.rerank import CrossEncoderReranker, FeatureReranker, Reranker
from ainma.retrieval.text import tokenize
from ainma.store.base import Store

logger = logging.getLogger(__name__)

_EPS = 1e-12


class SearchHit(Strict):
    chunk: Chunk
    passage: RankedPassage
    document: DocumentMeta


class SearchResult(BaseModel):
    """`hits` is the ranked top-k. Under A5 withdrawn documents never appear in `hits`: they are
    listed in `withdrawn` (with the score they would have had) so the pipeline can say so."""

    model_config = ConfigDict(frozen=True)

    hits: list[SearchHit]
    withdrawn: list[SearchHit]
    as_of: date | None
    n_candidates: int


EmbedderFactory = Callable[[RetrievalConfig], Embedder]
RerankerFactory = Callable[[RetrievalConfig], Reranker]


def default_embedder(config: RetrievalConfig) -> Embedder:
    if config.embedder == "fastembed":
        return FastEmbedEmbedder(config.embedder_model)
    return LsaEmbedder(dim=config.lsa_dim, seed=config.seed)


def default_reranker(config: RetrievalConfig) -> Reranker:
    if config.reranker == "cross_encoder":
        return CrossEncoderReranker(config.reranker_model)
    return FeatureReranker(config.reranker_weights)


class _FittedIndex:
    def __init__(self, chunks: list[Chunk], config: RetrievalConfig, embedder: Embedder) -> None:
        self.chunks = chunks
        self.bm25 = BM25Index(
            [tokenize(c.text) for c in chunks], k1=config.bm25_k1, b=config.bm25_b
        )
        embedder.fit([c.text for c in chunks])
        self.embedder = embedder
        self.matrix: NDArray[np.float64] = embedder.embed([c.text for c in chunks])
        self._facts: dict[int, list[ExtractedFact]] = {}

    def facts(self, index: int) -> list[ExtractedFact]:
        if index not in self._facts:
            self._facts[index] = extract_facts_rules(self.chunks[index].text)
        return self._facts[index]


def _fingerprint(chunks: Sequence[Chunk], config: RetrievalConfig) -> str:
    digest = hashlib.sha256()
    digest.update(
        repr(
            (
                config.embedder,
                config.embedder_model,
                config.lsa_dim,
                config.seed,
                config.bm25_k1,
                config.bm25_b,
            )
        ).encode()
    )
    for chunk in chunks:
        digest.update(f"\x00{chunk.id}\x00{chunk.text}".encode())
    return digest.hexdigest()


def _ranking(scores: NDArray[np.float64], ids: Sequence[str]) -> list[int]:
    """Indices with a positive score, best first, ties by chunk id (deterministic)."""
    positive = [i for i in range(len(ids)) if scores[i] > _EPS]
    return sorted(positive, key=lambda i: (-float(scores[i]), ids[i]))


class RetrievalEngine:
    def __init__(
        self,
        *,
        max_indexes: int = 8,
        embedder_factory: EmbedderFactory = default_embedder,
        reranker_factory: RerankerFactory = default_reranker,
    ) -> None:
        self._indexes: OrderedDict[str, _FittedIndex] = OrderedDict()
        self._max = max_indexes
        self._embedder_factory = embedder_factory
        self._reranker_factory = reranker_factory
        self._rerankers: dict[str, Reranker] = {}
        self.fits = 0  # number of index fits, for tests and diagnostics

    def _index(self, chunks: list[Chunk], config: RetrievalConfig) -> _FittedIndex:
        key = _fingerprint(chunks, config)
        if key in self._indexes:
            self._indexes.move_to_end(key)
            return self._indexes[key]
        index = _FittedIndex(chunks, config, self._embedder_factory(config))
        self.fits += 1
        self._indexes[key] = index
        while len(self._indexes) > self._max:
            self._indexes.popitem(last=False)
        return index

    def _reranker(self, config: RetrievalConfig) -> Reranker:
        key = config.model_dump_json(include={"reranker", "reranker_model", "reranker_weights"})
        if key not in self._rerankers:
            self._rerankers[key] = self._reranker_factory(config)
        return self._rerankers[key]

    async def search(
        self,
        query: str,
        *,
        store: Store,
        access: AccessContext,
        deal_id: str | None,
        config: RetrievalConfig | None = None,
        doc_types: Sequence[DocType] | None = None,
    ) -> SearchResult:
        config = config or RetrievalConfig()
        chunks = await store.candidates(access, deal_id=deal_id, doc_types=doc_types)
        if not chunks:
            return SearchResult(hits=[], withdrawn=[], as_of=None, n_candidates=0)
        documents = {d.id: d for d in await store.list_documents(access, deal_id)}
        dated = [c.published_on for c in chunks if c.published_on is not None]
        as_of = config.as_of or (max(dated) if dated else None)
        index = self._index(chunks, config)
        return self._rank(query, index, documents, config, as_of)

    def _rank(
        self,
        query: str,
        index: _FittedIndex,
        documents: dict[str, DocumentMeta],
        config: RetrievalConfig,
        as_of: date | None,
    ) -> SearchResult:
        chunks = index.chunks
        ids = [c.id for c in chunks]
        bm25 = index.bm25.scores(tokenize(query))
        dense = index.matrix @ index.embedder.embed([query])[0] if len(chunks) else bm25
        bm_rank, dn_rank = _ranking(bm25, ids), _ranking(dense, ids)
        bm_pos = {i: r for r, i in enumerate(bm_rank, start=1)}
        dn_pos = {i: r for r, i in enumerate(dn_rank, start=1)}
        fused = rrf_fuse([bm_rank, dn_rank], k=config.rrf_k, weights=config.rrf_weights)
        ceiling = rrf_ceiling(k=config.rrf_k, weights=config.rrf_weights)
        fused_order = sorted(fused, key=lambda i: (-fused[i], ids[i]))

        rerank: dict[int, float] = {}
        if config.system == "A1":
            order = bm_rank
            relevance = {i: float(bm25[i] / (bm25[i] + config.bm25_scale)) for i in order}
        elif config.system == "A2":
            order = dn_rank
            relevance = {i: float(min(1.0, dense[i])) for i in order}
        elif config.system == "A3":
            order = fused_order
            relevance = {i: fused[i] / ceiling for i in order}
        else:
            window = fused_order[: config.rerank_top]
            scores = self._reranker(config).score(query, [chunks[i].text for i in window])
            rerank = dict(zip(window, scores, strict=True))
            w = config.rerank_weight
            relevance = {i: w * rerank[i] + (1.0 - w) * fused[i] / ceiling for i in window}
            order = sorted(window, key=lambda i: (-relevance[i], window.index(i)))

        ranker = config.ranker
        facts_by_doc = (
            [(documents[chunks[i].document_id], index.facts(i)) for i in order]
            if config.system == "A5"
            else []
        )
        rows: list[tuple[int, dict[str, float], float, DocumentMeta]] = []
        for i in order:
            chunk = chunks[i]
            document = documents[chunk.document_id]
            tier_weight = ranker.tier_weights[document.tier]
            recency = chunk_recency(chunk, ranker, as_of)
            status = ranker.status_factors[document.status]
            bonus = 0.0
            if config.system == "A5":
                others = [pair for pair in facts_by_doc if pair[0].id != document.id]
                n_others = corroboration_count(
                    document, index.facts(i), others, ranker.corroboration_tolerance
                )
                bonus = corroboration_bonus(n_others, ranker) if status > 0 else 0.0
            components = {
                "bm25": float(bm25[i]),
                "dense": float(dense[i]),
                "rrf": float(fused.get(i, 0.0)),
                "rerank": float(rerank.get(i, 0.0)),
                "tier_weight": tier_weight,
                "recency": recency,
                "corroboration": bonus,
                "relevance": relevance[i],
                "status": status,
            }
            final = (
                final_score(
                    relevance=relevance[i],
                    tier_weight=tier_weight,
                    recency=recency,
                    status=status,
                    bonus=bonus,
                )
                if config.system == "A5"
                else relevance[i]
            )
            rows.append((i, components, final, document))

        if config.system == "A5":
            rows.sort(key=lambda r: (-r[2], -r[1]["relevance"], ids[r[0]]))
        withdrawn_rows = [
            r for r in rows if config.system == "A5" and r[3].status is DocStatus.WITHDRAWN
        ]
        kept = [r for r in rows if r not in withdrawn_rows]

        def to_hit(rank: int, row: tuple[int, dict[str, float], float, DocumentMeta]) -> SearchHit:
            i, components, final, document = row
            passage = RankedPassage(
                chunk_id=chunks[i].id,
                rank=rank,
                final_score=final,
                components=components,
                explanation=_explain(config, components, document, bm_pos.get(i), dn_pos.get(i)),
            )
            return SearchHit(chunk=chunks[i], passage=passage, document=document)

        hits = [to_hit(rank, row) for rank, row in enumerate(kept[: config.top_k], start=1)]
        withdrawn = [to_hit(rank, row) for rank, row in enumerate(withdrawn_rows, start=1)]
        return SearchResult(hits=hits, withdrawn=withdrawn, as_of=as_of, n_candidates=len(chunks))


def _explain(
    config: RetrievalConfig,
    c: dict[str, float],
    document: DocumentMeta,
    bm_rank: int | None,
    dn_rank: int | None,
) -> str:
    parts = [
        f"keyword rank {bm_rank}" if bm_rank else "no keyword match",
        f"dense rank {dn_rank}" if dn_rank else "no dense match",
    ]
    if config.system in ("A4", "A5"):
        parts.append(f"reranker {c['rerank']:.2f}")
    if config.system == "A5":
        parts.append(
            f"tier {int(document.tier)} {document.doc_type.value.replace('_', ' ')} "
            f"(weight {c['tier_weight']:.2f})"
        )
        parts.append(f"recency {c['recency']:.2f}")
        if document.status is not DocStatus.CURRENT:
            parts.append(f"{document.status.value} (factor {c['status']:.1f})")
        if c["corroboration"] > 0:
            parts.append(f"corroborated (+{c['corroboration']:.2f})")
    return "; ".join(parts) + "."
