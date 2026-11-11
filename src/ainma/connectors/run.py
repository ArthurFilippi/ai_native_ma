"""Ingest connector items into a deal space.

`python -m ainma.connectors.run --deal deal_aurora --seed-dir data/synthetic/1234 --user u_lead`

Each item becomes a one page document (`press_article` or `press_release`, `origin` set to
`simulated-connector`, `synthetic` true, a visible SYNTHETIC mark in the text). The document id is
derived from the item, so a rerun replaces the same documents instead of adding copies.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from ainma.connectors.base import Connector
from ainma.connectors.chunking import SYNTHETIC_MARK, chunk_page
from ainma.connectors.simulated import SimulatedNewsConnector
from ainma.contracts import AccessContext, ConnectorItem, DocType, DocumentMeta
from ainma.runtime import open_runtime
from ainma.settings import get_settings
from ainma.store import Store

logger = logging.getLogger(__name__)

_ALLOWED_TYPES = (DocType.PRESS_ARTICLE, DocType.PRESS_RELEASE)


def document_id_for(item: ConnectorItem, entity: str) -> str:
    """Stable id: the same connector, entity, title and date always give the same id."""
    key = "|".join((item.connector, entity, item.title, str(item.published_on)))
    return f"doc_news_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]}"


def _page_text(item: ConnectorItem) -> str:
    parts = [item.title, item.text]
    if item.simulated:
        parts.insert(0, SYNTHETIC_MARK)
    return "\n\n".join(parts)


async def _ingest_item(
    store: Store, deal_id: str, entity: str, item: ConnectorItem
) -> DocumentMeta:
    if item.doc_type not in _ALLOWED_TYPES:
        raise ValueError(f"connector items must be press articles or releases: {item.title!r}")
    page = _page_text(item)
    meta = DocumentMeta(
        id=document_id_for(item, entity),
        deal_id=deal_id,
        entity_id=entity,
        title=item.title,
        doc_type=item.doc_type,
        published_on=item.published_on or item.retrieved_on,
        n_pages=1,
        sha256=hashlib.sha256(page.encode("utf-8")).hexdigest(),
        synthetic=item.simulated,
        origin="simulated-connector" if item.simulated else "web",
    )
    await store.put_document(meta, [page])
    await store.put_chunks(chunk_page(meta, page))
    return meta


async def run_market_intel(
    deal_id: str,
    *,
    store: Store,
    access: AccessContext,
    seed_dir: Path,
    since: date = date.min,
) -> int:
    """Ingest every simulated news item (the deal's and its buyers') into the deal space.

    Returns the number of documents written. Raises `LookupError` when the deal does not exist
    or `access` does not give the user the deal.
    """
    if await store.get_deal(deal_id, access) is None:
        raise LookupError(f"deal {deal_id} not found")
    connector = SimulatedNewsConnector(seed_dir)
    return await ingest_from(connector, await connector.entities(), deal_id, store, since)


async def ingest_from(
    connector: Connector, entities: Sequence[str], deal_id: str, store: Store, since: date
) -> int:
    count = 0
    for entity in entities:
        for item in await connector.fetch(entity=entity, since=since):
            await _ingest_item(store, deal_id, entity, item)
            count += 1
    logger.info("ingested %d documents from %s into %s", count, connector.name, deal_id)
    return count


async def run_live_search(
    deal_id: str,
    query: str,
    *,
    store: Store,
    access: AccessContext,
    connector: Connector,
    since: date = date.min,
) -> list[DocumentMeta]:
    """File the live news a connector returns for `query` in the deal space (D99).

    Raises `LookupError` when the deal is not visible to `access`; a connector failure propagates
    (the API answers 503), it is never replaced by simulated items."""
    if await store.get_deal(deal_id, access) is None:
        raise LookupError(f"deal {deal_id} not found")
    items = await connector.fetch(entity=query, since=since)
    return [await _ingest_item(store, deal_id, "live", item) for item in items]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ainma.connectors.run")
    parser.add_argument("--deal", required=True, help="deal id, for example deal_aurora")
    parser.add_argument("--seed-dir", required=True, type=Path, help="data/synthetic/<seed>")
    parser.add_argument("--user", required=True, help="user id, for example u_lead")
    parser.add_argument("--since", type=date.fromisoformat, default=date.min, help="YYYY-MM-DD")
    return parser


async def _main(args: argparse.Namespace) -> int:
    runtime = await open_runtime(get_settings())
    try:
        access = await runtime.store.access_for(args.user)
        count = await run_market_intel(
            args.deal, store=runtime.store, access=access, seed_dir=args.seed_dir, since=args.since
        )
    finally:
        await runtime.close()
    sys.stdout.write(f"ingested {count} simulated documents into {args.deal}\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
