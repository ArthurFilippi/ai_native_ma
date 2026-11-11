from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import pytest

from ainma.connectors.chunking import MAX_CHARS, chunk_page
from ainma.connectors.run import document_id_for, main, run_market_intel
from ainma.connectors.simulated import SimulatedNewsConnector
from ainma.contracts import (
    ConnectorItem,
    CriterionStatus,
    DocType,
    DocumentMeta,
    ScreeningRequest,
)
from ainma.llm import MockLLM
from ainma.screening import run_screening
from ainma.store import SqliteStore
from tests.fixtures_biz.data_room import DEAL_ID
from tests.fixtures_biz.keyword_search import keyword_search
from tests.fixtures_biz.universe import BUYERS, load_universe

ITEMS = [
    {
        "connector": "simulated-news",
        "retrieved_on": "2025-06-01",
        "title": "Aurora wins a framework contract",
        "published_on": "2025-05-20",
        "doc_type": "press_article",
        "text": "Aurora signed a three year framework contract with a rail supplier.",
        "simulated": True,
        "entity": "deal_aurora",
    },
    {
        "connector": "simulated-news",
        "retrieved_on": "2025-06-01",
        "title": "Lonely Equity Fund II buys a casting business",
        "published_on": "2025-04-02",
        "doc_type": "press_release",
        "text": "Lonely Equity Fund II acquired a casting business in industrial components.",
        "simulated": True,
        "entity": "b_lonely",
    },
    {
        "connector": "simulated-news",
        "retrieved_on": "2025-06-01",
        "title": "Aurora old award",
        "published_on": "2023-01-10",
        "doc_type": "press_article",
        "text": "Aurora received a supplier award.",
        "simulated": True,
        "entity": "deal_aurora",
    },
    {
        "connector": "simulated-news",
        "retrieved_on": "2025-06-01",
        "title": "Undated Aurora note",
        "published_on": None,
        "doc_type": "press_article",
        "text": "Aurora opens a new plant.",
        "simulated": True,
        "entity": "deal_aurora",
    },
]


def _seed(tmp_path: Path, items: list[dict[str, object]] | None = None) -> Path:
    seed = tmp_path / "1234"
    (seed / "news").mkdir(parents=True, exist_ok=True)
    (seed / "news" / "items.json").write_text(json.dumps(items or ITEMS), encoding="utf-8")
    return seed


@pytest.fixture
async def store() -> AsyncIterator[SqliteStore]:
    opened = await SqliteStore.open(":memory:")
    await load_universe(opened)
    yield opened
    await opened.close()


async def test_connector_filters_by_entity_and_date_and_is_deterministic(tmp_path: Path) -> None:
    connector = SimulatedNewsConnector(_seed(tmp_path))
    assert connector.simulated is True and connector.name == "simulated-news"
    items = await connector.fetch(entity="deal_aurora", since=date(2024, 1, 1))
    assert [i.title for i in items] == [
        "Aurora wins a framework contract",
        "Undated Aurora note",
    ]  # the undated item falls back to its retrieval date (2025-06-01), oldest first
    assert items == await connector.fetch(entity="deal_aurora", since=date(2024, 1, 1))
    assert await connector.fetch(entity="b_missing", since=date.min) == []
    assert await connector.entities() == ["b_lonely", "deal_aurora"]
    everything = await connector.fetch(entity="deal_aurora", since=date.min)
    assert len(everything) == 3


async def test_run_market_intel_ingests_marked_chunked_documents(
    store: SqliteStore, tmp_path: Path
) -> None:
    access = await store.access_for("u_lead")
    before = {d.id for d in await store.list_documents(access, DEAL_ID)}
    count = await run_market_intel(DEAL_ID, store=store, access=access, seed_dir=_seed(tmp_path))
    assert count == 4
    new = [d for d in await store.list_documents(access, DEAL_ID) if d.id not in before]
    assert len(new) == 4
    for meta in new:
        assert meta.origin == "simulated-connector" and meta.synthetic
        assert meta.doc_type in (DocType.PRESS_ARTICLE, DocType.PRESS_RELEASE)
        assert meta.deal_id == DEAL_ID and meta.entity_id in {"deal_aurora", "b_lonely"}
        page = await store.get_page(meta.id, 1, access)
        assert page is not None and "SYNTHETIC" in page
        chunks = [
            c for c in await store.candidates(access, deal_id=DEAL_ID) if c.document_id == meta.id
        ]
        assert chunks and all(page[c.char_start : c.char_end] == c.text for c in chunks)
        assert all(
            c.entity_id == meta.entity_id and c.published_on == meta.published_on for c in chunks
        )
    release = next(m for m in new if m.entity_id == "b_lonely")
    assert release.doc_type is DocType.PRESS_RELEASE and release.published_on == date(2025, 4, 2)


async def test_rerun_is_idempotent(store: SqliteStore, tmp_path: Path) -> None:
    access = await store.access_for("u_lead")
    seed = _seed(tmp_path)
    await run_market_intel(DEAL_ID, store=store, access=access, seed_dir=seed)
    first_docs = await store.list_documents(access, DEAL_ID)
    first_chunks = await store.candidates(access, deal_id=DEAL_ID)
    again = await run_market_intel(DEAL_ID, store=store, access=access, seed_dir=seed)
    assert again == 4
    assert await store.list_documents(access, DEAL_ID) == first_docs
    assert await store.candidates(access, deal_id=DEAL_ID) == first_chunks


async def test_a_user_outside_the_deal_cannot_ingest(store: SqliteStore, tmp_path: Path) -> None:
    outsider = await store.access_for("u_outsider")
    with pytest.raises(LookupError):
        await run_market_intel(DEAL_ID, store=store, access=outsider, seed_dir=_seed(tmp_path))
    lead = await store.access_for("u_lead")
    with pytest.raises(LookupError):
        await run_market_intel("deal_nope", store=store, access=lead, seed_dir=_seed(tmp_path))


async def test_only_press_documents_are_accepted(store: SqliteStore, tmp_path: Path) -> None:
    bad = [{**ITEMS[0], "doc_type": "web"}]
    lead = await store.access_for("u_lead")
    with pytest.raises(ValueError, match="press articles or releases"):
        await run_market_intel(DEAL_ID, store=store, access=lead, seed_dir=_seed(tmp_path, bad))


def test_document_ids_are_derived_from_the_item() -> None:
    item = ConnectorItem.model_validate({k: v for k, v in ITEMS[0].items() if k != "entity"})
    other = item.model_copy(update={"title": "Another title"})
    assert document_id_for(item, "deal_aurora") == document_id_for(item, "deal_aurora")
    assert document_id_for(item, "deal_aurora") != document_id_for(other, "deal_aurora")
    assert document_id_for(item, "deal_aurora") != document_id_for(item, "b_lonely")


def test_long_paragraphs_are_cut_at_sentences_with_exact_offsets() -> None:
    sentence = "Aurora delivered another solid quarter of growth. "
    text = "SYNTHETIC DOCUMENT, fictional data.\n\nTitle\n\n" + sentence * 40 + "x" * 2000
    meta = DocumentMeta(
        id="doc_x",
        deal_id=DEAL_ID,
        title="t",
        doc_type=DocType.PRESS_ARTICLE,
        n_pages=1,
        sha256="0" * 64,
    )
    chunks = chunk_page(meta, text)
    assert len(chunks) > 3
    assert all(text[c.char_start : c.char_end] == c.text for c in chunks)
    assert all(len(c.text) <= MAX_CHARS for c in chunks)
    assert not any("SYNTHETIC DOCUMENT" in c.text for c in chunks)
    assert [c.id for c in chunks] == [f"doc_x_p1_{i:02d}" for i in range(len(chunks))]


async def test_ingested_news_becomes_screening_evidence(store: SqliteStore, tmp_path: Path) -> None:
    lead = await store.access_for("u_lead")
    request = ScreeningRequest(deal_id=DEAL_ID)

    async def lonely_activity() -> CriterionStatus:
        result = await run_screening(
            request,
            store=store,
            access=lead,
            llm=MockLLM({}),
            buyers=BUYERS,
            search=keyword_search,
        )
        (card,) = [c for c in result.cards if c.buyer.id == "b_lonely"]
        return {r.criterion_key: r.status for r in card.results}["recent_activity"]

    assert await lonely_activity() is CriterionStatus.UNKNOWN
    await run_market_intel(DEAL_ID, store=store, access=lead, seed_dir=_seed(tmp_path))
    assert await lonely_activity() is CriterionStatus.MET


async def _prepare(db: Path) -> None:
    opened = await SqliteStore.open(db)
    await load_universe(opened)
    await opened.close()


async def _simulated_documents(db: Path) -> int:
    reopened = await SqliteStore.open(db)
    docs = await reopened.list_documents(await reopened.access_for("u_lead"), DEAL_ID)
    await reopened.close()
    return sum(d.origin == "simulated-connector" for d in docs)


def test_cli_ingests_into_the_configured_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.sqlite"
    asyncio.run(_prepare(db))
    monkeypatch.setenv("SQLITE_PATH", str(db))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    argv = ["--deal", DEAL_ID, "--seed-dir", str(_seed(tmp_path)), "--user", "u_lead"]
    assert main(argv) == 0
    assert "ingested 4 simulated documents into deal_aurora" in capsys.readouterr().out
    assert main(argv) == 0  # a rerun does not add copies
    assert asyncio.run(_simulated_documents(db)) == 4


async def test_filing_the_feed_in_a_second_deal_keeps_the_first_deals_copy(
    store: SqliteStore, tmp_path: Path
) -> None:
    """Regression: the document id ignored the deal, so filing the same feed in deal B moved the
    documents out of deal A (an `INSERT OR REPLACE` on the same id)."""
    from ainma.contracts import Deal, Membership, Role

    await store.put_deal(Deal(id="deal_other", name="Project Other", sector="software"))
    await store.put_membership(Membership(deal_id="deal_other", user_id="u_lead", role=Role.LEAD))
    lead = await store.access_for("u_lead")
    seed = _seed(tmp_path)
    first = await run_market_intel(DEAL_ID, store=store, access=lead, seed_dir=seed)
    await run_market_intel("deal_other", store=store, access=lead, seed_dir=seed)
    kept = [
        d for d in await store.list_documents(lead, DEAL_ID) if d.origin == "simulated-connector"
    ]
    assert len(kept) == first
