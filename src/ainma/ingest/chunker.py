"""Structure aware chunking: every chunk is an exact slice of its page text.

Rules: a heading starts a new chunk; consecutive text blocks are merged while the span stays
under `max_chars`; an oversized block is cut at sentence boundaries; a table is chunked on row
boundaries (a row is never split) and never merged with text. Chunk ids are
`ch_<doc>_p<page>_<nn>`, `nn` counting from 01 inside the page.
"""

from __future__ import annotations

import re

from ainma.contracts import Chunk, DocumentMeta
from ainma.ingest.base import BlockSpan, ParsedDocument, ParsedPage

MAX_CHARS = 900
MAX_TABLE_CHARS = 1400
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")


def chunk_id(document_id: str, page: int, index: int) -> str:
    stem = document_id.removeprefix("doc_")
    return f"ch_{stem}_p{page}_{index:02d}"


def _sentence_spans(page_text: str, block: BlockSpan, max_chars: int) -> list[tuple[int, int]]:
    """Cut one oversized block into spans of whole sentences, each under `max_chars` if possible."""
    text = page_text[block.start : block.end]
    cuts = [0]
    for match in _SENTENCE_END.finditer(text):
        cuts.append(match.end())
    cuts.append(len(text))
    spans: list[tuple[int, int]] = []
    start = 0
    last_ok = 0
    for i in range(1, len(cuts)):
        if cuts[i] - start > max_chars and last_ok > start:
            spans.append((start, last_ok))
            start = last_ok
        last_ok = cuts[i]
    spans.append((start, len(text)))
    return [(block.start + a, block.start + b) for a, b in spans if text[a:b].strip()]


def _trim(page_text: str, start: int, end: int) -> tuple[int, int]:
    segment = page_text[start:end]
    lead = len(segment) - len(segment.lstrip())
    trail = len(segment) - len(segment.rstrip())
    return start + lead, end - trail


def _table_spans(page_text: str, block: BlockSpan, max_chars: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    group_start: int | None = None
    group_end = block.start
    cursor = block.start
    for line in page_text[block.start : block.end].split("\n"):
        line_start, line_end = cursor, cursor + len(line)
        cursor = line_end + 1
        if group_start is None:
            group_start, group_end = line_start, line_end
        elif line_end - group_start > max_chars:
            spans.append((group_start, group_end))
            group_start, group_end = line_start, line_end
        else:
            group_end = line_end
    if group_start is not None:
        spans.append((group_start, group_end))
    return spans


def _chunk_page(
    meta: DocumentMeta, page_no: int, page: ParsedPage, max_chars: int, max_table_chars: int
) -> list[Chunk]:
    out: list[Chunk] = []

    def emit(start: int, end: int, kind: str) -> None:
        start, end = _trim(page.text, start, end)
        if end <= start:
            return
        out.append(
            Chunk(
                id=chunk_id(meta.id, page_no, len(out) + 1),
                document_id=meta.id,
                deal_id=meta.deal_id,
                entity_id=meta.entity_id,
                page=page_no,
                char_start=start,
                char_end=end,
                text=page.text[start:end],
                kind="table" if kind == "table" else "text",
                doc_type=meta.doc_type,
                published_on=meta.published_on,
            )
        )

    group: tuple[int, int] | None = None
    heading_only = False

    def flush() -> None:
        nonlocal group, heading_only
        if group is not None:
            emit(group[0], group[1], "text")
        group = None
        heading_only = False

    for block in page.blocks:
        if block.kind == "table":
            lead: tuple[int, int] | None = None
            if group is not None and heading_only:
                lead, group, heading_only = group, None, False  # heading titles its table
            flush()
            for index, (start, end) in enumerate(_table_spans(page.text, block, max_table_chars)):
                emit(lead[0] if lead is not None and index == 0 else start, end, "table")
            continue
        if block.kind == "heading":
            flush()
            heading_only = True
        else:
            heading_only = False
        pieces = (
            _sentence_spans(page.text, block, max_chars)
            if block.end - block.start > max_chars
            else [(block.start, block.end)]
        )
        for start, end in pieces:
            if group is not None and end - group[0] > max_chars:
                flush()
            group = (start, end) if group is None else (group[0], end)
    flush()
    return out


def chunk_document(
    meta: DocumentMeta,
    parsed: ParsedDocument,
    *,
    max_chars: int = MAX_CHARS,
    max_table_chars: int = MAX_TABLE_CHARS,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page_no, page in enumerate(parsed.pages, start=1):
        chunks.extend(_chunk_page(meta, page_no, page, max_chars, max_table_chars))
    return chunks
