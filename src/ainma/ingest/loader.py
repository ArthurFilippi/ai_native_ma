"""Load a generated seed directory into a store: deals, users, memberships, documents, chunks."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter

from ainma.contracts import BuyerProfile, Deal, DocumentMeta
from ainma.ingest.base import ParsedDocument
from ainma.ingest.chunker import chunk_document
from ainma.ingest.parse import parse_file
from ainma.store.base import Store
from ainma.truth import ManifestEntry, UsersFile

_MANIFEST = TypeAdapter(list[ManifestEntry])
_DEALS = TypeAdapter(list[Deal])
_BUYERS = TypeAdapter(list[BuyerProfile])


@dataclass(frozen=True)
class LoadReport:
    documents: int
    chunks: int


def meta_from_entry(entry: ManifestEntry, parsed: ParsedDocument, data: bytes) -> DocumentMeta:
    """Manifest entry plus what only the parser knows: page count and file hash."""
    return DocumentMeta(
        id=entry.id,
        deal_id=entry.deal_id,
        entity_id=entry.entity_id,
        title=entry.title,
        doc_type=entry.doc_type,
        published_on=entry.published_on,
        status=entry.status,
        superseded_by=entry.superseded_by,
        n_pages=len(parsed.pages),
        sha256=hashlib.sha256(data).hexdigest(),
        synthetic=entry.synthetic,
        origin=entry.origin,
    )


def read_manifest(seed_dir: Path) -> list[ManifestEntry]:
    return _MANIFEST.validate_json((seed_dir / "manifest.json").read_bytes())


def _parse_entry(seed_dir: Path, entry: ManifestEntry) -> tuple[DocumentMeta, ParsedDocument]:
    path = seed_dir / entry.path
    data = path.read_bytes()
    parsed = parse_file(path)
    return meta_from_entry(entry, parsed, data), parsed


async def load_corpus(store: Store, seed_dir: Path) -> LoadReport:
    seed_dir = Path(seed_dir)
    truth = seed_dir / "truth"
    for deal in _DEALS.validate_json((truth / "deals.json").read_bytes()):
        await store.put_deal(deal)
    users = UsersFile.model_validate(json.loads((truth / "users.json").read_text("utf-8")))
    for user in users.users:
        await store.put_user(user)
    for membership in users.memberships:
        await store.put_membership(membership)
    for buyer in _BUYERS.validate_json((truth / "buyers.json").read_bytes()):
        await store.put_buyer(buyer)
    documents = 0
    chunks = 0
    for entry in read_manifest(seed_dir):
        meta, parsed = await asyncio.to_thread(_parse_entry, seed_dir, entry)
        await store.put_document(meta, parsed.page_texts)
        doc_chunks = chunk_document(meta, parsed)
        await store.put_chunks(doc_chunks)
        documents += 1
        chunks += len(doc_chunks)
    return LoadReport(documents=documents, chunks=chunks)
