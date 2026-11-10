"""Tiny chunker for one page documents: paragraphs, with exact offsets inside the page text.

The store requires `chunk.text == page_text[char_start:char_end]` (decision D04). Paragraphs longer
than `MAX_CHARS` are cut at sentence ends. The mark paragraph is part of the page but not chunked.
"""

from __future__ import annotations

import re

from ainma.contracts import Chunk, DocumentMeta

MAX_CHARS = 700
SYNTHETIC_MARK = "SYNTHETIC DOCUMENT, fictional data."
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _pieces(paragraph: str, offset: int) -> list[tuple[int, int]]:
    """Spans of at most MAX_CHARS inside `paragraph`: whole sentences packed greedily, and a
    hard cut for a single sentence longer than the limit."""
    sentences: list[tuple[int, int]] = []
    position = 0
    for match in _SENTENCE_END.finditer(paragraph):
        sentences.append((position, match.start()))
        position = match.end()
    sentences.append((position, len(paragraph)))

    packed: list[tuple[int, int]] = []
    start, end = sentences[0]
    for next_start, next_end in sentences[1:]:
        if next_end - start <= MAX_CHARS:
            end = next_end
        else:
            packed.append((start, end))
            start, end = next_start, next_end
    packed.append((start, end))

    spans: list[tuple[int, int]] = []
    for a, b in packed:
        while b - a > MAX_CHARS:
            spans.append((offset + a, offset + a + MAX_CHARS))
            a += MAX_CHARS
        spans.append((offset + a, offset + b))
    return spans


def chunk_page(meta: DocumentMeta, page_text: str) -> list[Chunk]:
    """Chunks of page 1 of `meta`, ids `<document id>_p1_<nn>`."""
    chunks: list[Chunk] = []
    cursor = 0
    for paragraph in page_text.split("\n\n"):
        start = page_text.index(paragraph, cursor)
        cursor = start + len(paragraph)
        if not paragraph.strip() or paragraph.strip() == SYNTHETIC_MARK:
            continue
        for a, b in _pieces(paragraph, start):
            chunks.append(
                Chunk(
                    id=f"{meta.id}_p1_{len(chunks):02d}",
                    document_id=meta.id,
                    deal_id=meta.deal_id,
                    entity_id=meta.entity_id,
                    page=1,
                    char_start=a,
                    char_end=b,
                    text=page_text[a:b],
                    doc_type=meta.doc_type,
                    published_on=meta.published_on,
                )
            )
    return chunks
