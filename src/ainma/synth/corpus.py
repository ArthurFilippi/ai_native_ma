"""Build every document of a seed, write the files, parse them back and resolve fact spans."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from ainma.contracts import Chunk, DocStatus, DocumentMeta
from ainma.ingest.chunker import chunk_document
from ainma.ingest.parse import parse_file
from ainma.synth.builder import FactBook
from ainma.synth.common import Params, rng_for
from ainma.synth.docs_buyers import build_buyer_docs, build_news
from ainma.synth.docs_company import (
    Ctx,
    build_article,
    build_article2,
    build_board,
    build_cim,
    build_concentration,
    build_mgmt,
    build_model,
    build_nda,
    build_old_article,
    build_old_deck,
    build_pr,
    build_pr_pair,
    build_qoe,
    build_spa,
    days,
)
from ainma.synth.docs_kb import build_kb
from ainma.synth.docspec import DocSpec
from ainma.synth.lang import NamePool
from ainma.synth.news_events import build_news_events
from ainma.synth.truthio import Fact, ManifestEntry, NewsItem
from ainma.synth.world import (
    OLD_DECK_DEALS,
    SPA_DEALS,
    WITHDRAWN_PR_DEALS,
    World,
    build_world,
)
from ainma.synth.writers import render
from ainma.truth import NewsEventTruth


@dataclass(frozen=True)
class Occurrence:
    document_id: str
    page: int
    char_start: int
    char_end: int
    quote: str


@dataclass
class Corpus:
    params: Params
    world: World
    specs: list[DocSpec]
    book: FactBook
    news: list[NewsItem]
    facts: list[Fact] = field(default_factory=list)
    occurrences: dict[str, list[Occurrence]] = field(default_factory=dict)
    chunks: dict[str, list[Chunk]] = field(default_factory=dict)
    pages: dict[str, list[str]] = field(default_factory=dict)
    metas: dict[str, DocumentMeta] = field(default_factory=dict)
    published_acquisitions: set[tuple[str, str]] = field(default_factory=set)
    news_events: list[NewsEventTruth] = field(default_factory=list)

    def spec(self, doc_id: str) -> DocSpec:
        return next(s for s in self.specs if s.id == doc_id)


def _pick(rng_choice: float, start: date, end: date) -> date:
    return start + timedelta(days=int((end - start).days * rng_choice))


def _deal_specs(world: World, book: FactBook) -> list[DocSpec]:
    params = world.params
    specs: list[DocSpec] = []
    for comp in world.companies:
        ctx = Ctx(comp, book, params)
        rng = rng_for(params.seed, "dates", comp.deal_id)
        if comp.deal_id == "deal_aurora":
            specs.extend(_aurora_specs(ctx))
            continue
        k = comp.key
        cim_d = _pick(rng.random(), date(2025, 2, 15), date(2025, 4, 20))
        art_d = _pick(rng.random(), date(2025, 1, 12), cim_d - timedelta(days=3))
        specs.append(build_cim(ctx, f"doc_{k}_cim", cim_d, big=False))
        specs.append(build_mgmt(ctx, f"doc_{k}_mgmt", days(cim_d, 14)))
        specs.append(build_article(ctx, f"doc_{k}_news", art_d, aurora=False))
        if comp.deal_id in WITHDRAWN_PR_DEALS:
            orig, corr = build_pr_pair(
                ctx, f"doc_{k}_pr_orig", f"doc_{k}_pr_corr", days(cim_d, 10), days(cim_d, 14)
            )
            specs.extend([orig, corr])
        else:
            specs.append(build_pr(ctx, f"doc_{k}_pr", days(cim_d, 20)))
        if comp.deal_id in SPA_DEALS:
            specs.append(
                build_spa(
                    ctx,
                    f"doc_{k}_spa_draft",
                    days(cim_d, 30),
                    draft=True,
                    superseded_by=f"doc_{k}_spa_exec",
                )
            )
            specs.append(build_spa(ctx, f"doc_{k}_spa_exec", days(cim_d, 60), draft=False))
        specs.append(
            build_old_article(
                ctx, f"doc_{k}_news_old", _pick(rng.random(), date(2024, 2, 1), date(2024, 11, 30))
            )
        )
        if comp.deal_id in OLD_DECK_DEALS:
            specs.append(
                build_old_deck(
                    ctx,
                    f"doc_{k}_deck_old",
                    _pick(rng.random(), date(2023, 2, 1), date(2023, 6, 30)),
                )
            )
    return specs


def _aurora_specs(ctx: Ctx) -> list[DocSpec]:
    specs = [
        build_cim(ctx, "doc_cim", date(2025, 3, 14), big=True),
        build_mgmt(ctx, "doc_mgmt_pres", date(2025, 3, 28)),
        build_model(ctx, "doc_model", date(2025, 3, 10)),
        build_nda(ctx, "doc_nda", date(2025, 1, 20)),
        build_spa(
            ctx, "doc_spa_draft", date(2025, 4, 10), draft=True, superseded_by="doc_spa_exec"
        ),
        build_spa(ctx, "doc_spa_exec", date(2025, 5, 20), draft=False),
        build_board(ctx, "doc_board_minutes", date(2025, 2, 18)),
        build_qoe(ctx, "doc_qoe", date(2025, 3, 5)),
        build_concentration(ctx, "doc_concentration", date(2025, 3, 10)),
    ]
    orig, corr = build_pr_pair(
        ctx, "doc_pr_orig", "doc_pr_corr", date(2025, 2, 10), date(2025, 2, 14)
    )
    specs.extend([orig, corr])
    specs.append(build_article(ctx, "doc_news_17", date(2025, 2, 2), aurora=True))
    specs.append(build_article2(ctx, "doc_news_22", date(2025, 4, 22)))
    specs.append(build_old_article(ctx, "doc_news_old", date(2024, 3, 12)))
    return specs


def build_specs(params: Params) -> Corpus:
    world = build_world(params)
    book = FactBook()
    names = NamePool(rng_for(params.seed, "kbnames"))
    for c in world.companies:
        names.reserve(c.name)
    specs: list[DocSpec] = build_kb(params, book, names)
    specs.extend(_deal_specs(world, book))
    published: set[tuple[str, str]] = set()
    for buyer in world.buyers:
        bd = build_buyer_docs(world, buyer, book)
        specs.extend(bd.docs)
        published |= bd.published_acquisitions
    news = build_news(world, published)
    extra, events = build_news_events(world, news)
    return Corpus(
        params,
        world,
        specs,
        book,
        [*news, *extra],
        published_acquisitions=published,
        news_events=events,
    )


def _find_all(text: str, quote: str) -> list[int]:
    out: list[int] = []
    start = 0
    while True:
        i = text.find(quote, start)
        if i < 0:
            return out
        out.append(i)
        start = i + len(quote)


def materialize(corpus: Corpus, out_dir: Path) -> None:
    """Write files under `out_dir`, parse them back, chunk, and resolve every planted span."""
    for spec in corpus.specs:
        data = render(spec)
        path = out_dir / spec.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        parsed = parse_file(path)
        meta = DocumentMeta(
            id=spec.id,
            deal_id=spec.deal_id,
            entity_id=spec.entity_id,
            title=spec.title,
            doc_type=spec.doc_type,
            published_on=spec.published_on,
            status=spec.status,
            superseded_by=spec.superseded_by,
            n_pages=len(parsed.pages),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        chunks = chunk_document(meta, parsed)
        corpus.metas[spec.id] = meta
        corpus.chunks[spec.id] = chunks
        corpus.pages[spec.id] = parsed.page_texts
        # locate planted quotes: events with equal quotes consume successive positions
        positions: dict[str, list[tuple[int, int]]] = {}
        cursor: dict[str, int] = {}
        for quote, _ in spec.events():
            if quote not in positions:
                found = [
                    (page_no, i)
                    for page_no, text in enumerate(parsed.page_texts, start=1)
                    for i in _find_all(text, quote)
                ]
                positions[quote] = found
        for quote, fact_ids in spec.events():
            n = cursor.get(quote, 0)
            cursor[quote] = n + 1
            if n >= len(positions[quote]):
                raise ValueError(f"{spec.id}: planted quote not found in parsed text: {quote!r}")
            page_no, start = positions[quote][n]
            occ = Occurrence(spec.id, page_no, start, start + len(quote), quote)
            if not any(
                c.page == page_no and c.char_start <= occ.char_start and occ.char_end <= c.char_end
                for c in chunks
            ):
                raise ValueError(f"{spec.id}: no chunk contains the quote {quote!r}")
            for fid in fact_ids:
                corpus.occurrences.setdefault(fid, []).append(occ)
    for draft in corpus.book.facts.values():
        occs = corpus.occurrences[draft.id]
        primary = occs[0]
        support = [
            c.id
            for c in corpus.chunks[draft.doc_id]
            for o in occs
            if c.page == o.page and c.char_start <= o.char_start and o.char_end <= c.char_end
        ]
        support = list(dict.fromkeys(support))
        corpus.facts.append(
            Fact(
                id=draft.id,
                deal_id=draft.deal_id,
                entity=draft.entity,
                metric=draft.metric,
                period=draft.period,
                value=draft.value,
                unit=draft.unit,
                document_id=draft.doc_id,
                page=primary.page,
                char_start=primary.char_start,
                char_end=primary.char_end,
                quote=primary.quote,
                support_chunk_ids=support,
                keywords=draft.keywords,
            )
        )


def manifest_entries(corpus: Corpus) -> list[ManifestEntry]:
    return [
        ManifestEntry(
            id=s.id,
            path=s.path,
            format=s.fmt,
            deal_id=s.deal_id,
            entity_id=s.entity_id,
            title=s.title,
            doc_type=s.doc_type,
            published_on=s.published_on,
            status=s.status,
            superseded_by=s.superseded_by,
        )
        for s in corpus.specs
    ]


def is_current(corpus: Corpus, doc_id: str) -> bool:
    return corpus.spec(doc_id).status is DocStatus.CURRENT


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
