"""Request and response bodies that are not already contracts."""

from __future__ import annotations

from pydantic import Field

from ainma.contracts import Chunk, DocumentMeta, Strict


class AskRequest(Strict):
    question: str = Field(min_length=1, max_length=2000)


class HealthResponse(Strict):
    status: str
    auth: str
    llm_provider: str
    store_backend: str


class PassageResponse(Strict):
    """A chunk with its document and, on request, the page text.

    `highlight_start` and `highlight_end` are offsets inside `page_text` and always satisfy
    `page_text[highlight_start:highlight_end] == chunk.text`. A citation span lies inside it.
    """

    chunk: Chunk
    document: DocumentMeta
    page_text: str | None = None
    highlight_start: int = Field(ge=0)
    highlight_end: int


class MarketIntelRun(Strict):
    deal_id: str
    ingested: int = Field(ge=0)
