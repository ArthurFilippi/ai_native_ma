"""Test doubles and helpers owned by the `core` tests."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import date

from pydantic import BaseModel

from ainma.contracts import Chunk, DocStatus, DocType, DocumentMeta
from ainma.llm import LLM, Usage, build_mock_llm
from ainma.llm.tasks import TASK_WRITE
from ainma.pipeline.schemas import DraftClaim, DraftEvidence, WriteResult
from ainma.store.base import Store
from tests.fixtures.tiny import MARK, TinyDoc, chunk_document


class ScriptedWriter:
    """Mock for every task except `write`, which returns a scripted result."""

    provider = "mock"
    model = "scripted"

    def __init__(self, script: Callable[[], WriteResult]) -> None:
        self._script = script
        self._mock = build_mock_llm()

    async def complete_json[T: BaseModel](
        self, *, task: str, system: str, user: str, schema: type[T], stage: str
    ) -> tuple[T, Usage]:
        if task == TASK_WRITE:
            result = self._script()
            assert isinstance(result, schema)
            return result, Usage(provider=self.provider, model=self.model)
        return await self._mock.complete_json(
            task=task, system=system, user=user, schema=schema, stage=stage
        )


def draft(draft_id: str, text: str, passage: int, quote: str) -> DraftClaim:
    return DraftClaim(
        id=draft_id,
        text=text,
        status="sourced",
        evidence=[DraftEvidence(passage=passage, quote=quote)],
    )


def as_llm(llm: ScriptedWriter) -> LLM:
    return llm


def meta_of(chunk: Chunk, documents: list[DocumentMeta]) -> DocumentMeta:
    return next(d for d in documents if d.id == chunk.document_id)


async def add_doc(
    store: Store,
    doc_id: str,
    text: str,
    *,
    doc_type: DocType = DocType.PRESS_ARTICLE,
    published_on: date = date(2025, 3, 1),
    deal_id: str | None = "deal_aurora",
    status: DocStatus = DocStatus.CURRENT,
    superseded_by: str | None = None,
    sha: str | None = None,
) -> None:
    """Store a one page document, chunked into paragraphs like the tiny corpus."""
    pages = [f"{MARK}\n\n{text}"]
    digest = sha or hashlib.sha256(text.encode()).hexdigest()
    meta = DocumentMeta(
        id=doc_id,
        deal_id=deal_id,
        title=f"Test document {doc_id}",
        doc_type=doc_type,
        published_on=published_on,
        status=status,
        superseded_by=superseded_by,
        n_pages=1,
        sha256=digest,
    )
    doc = TinyDoc(meta, pages)
    await store.put_document(meta, pages)
    await store.put_chunks(chunk_document(doc))
