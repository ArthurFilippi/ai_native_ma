"""Shared parsing types and the pagination and rendering rules of the page text.

Page text is built first, chunks are slices of it (store invariant D04). A page is a sequence of
blocks joined by a blank line. Table rows inside a block are joined by a single newline, cells by
" | ".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

BlockKind = Literal["heading", "text", "table"]

BLOCK_SEP = "\n\n"
CELL_SEP = " | "
# Logical page rule for formats without physical pages (DOCX without page breaks, TXT without
# form feeds): a page is closed at a block boundary once it would exceed this many characters.
PAGE_CHAR_LIMIT = 4000


@dataclass(frozen=True)
class BlockSpan:
    start: int
    end: int
    kind: BlockKind


@dataclass(frozen=True)
class ParsedPage:
    text: str
    blocks: tuple[BlockSpan, ...]


@dataclass(frozen=True)
class ParsedDocument:
    pages: tuple[ParsedPage, ...]

    @property
    def page_texts(self) -> list[str]:
        return [p.text for p in self.pages]


def fmt_cell(value: object) -> str:
    """Canonical text of a table cell. Floats always print one decimal, so `168.0` stays `168.0`."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def row_text(cells: Sequence[object]) -> str:
    """One table row as page text: cells joined by ` | `, trailing empty cells dropped."""
    texts = [fmt_cell(c) for c in cells]
    while texts and texts[-1] == "":
        texts.pop()
    return CELL_SEP.join(texts)


def build_page(items: Iterable[tuple[BlockKind, str]]) -> ParsedPage:
    parts: list[str] = []
    blocks: list[BlockSpan] = []
    cursor = 0
    for kind, text in items:
        if not text:
            continue
        if parts:
            cursor += len(BLOCK_SEP)
        blocks.append(BlockSpan(cursor, cursor + len(text), kind))
        parts.append(text)
        cursor += len(text)
    return ParsedPage(BLOCK_SEP.join(parts), tuple(blocks))


def paginate(
    items: Iterable[tuple[BlockKind, str] | None], limit: int = PAGE_CHAR_LIMIT
) -> tuple[ParsedPage, ...]:
    """Group blocks into logical pages. `None` is an explicit page break."""
    pages: list[ParsedPage] = []
    current: list[tuple[BlockKind, str]] = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            pages.append(build_page(current))
        current = []
        size = 0

    for item in items:
        if item is None:
            flush()
            continue
        _, text = item
        if not text:
            continue
        if current and size + len(BLOCK_SEP) + len(text) > limit:
            flush()
        size += len(text) + (len(BLOCK_SEP) if current else 0)
        current.append(item)
    flush()
    if not pages:
        pages.append(ParsedPage("", ()))
    return tuple(pages)
