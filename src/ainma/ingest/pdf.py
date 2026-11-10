"""PDF parser: pypdf text fragments grouped into blocks by font and vertical gaps.

Convention shared with the generator's writer: body text is a proportional font, wrapped at
spaces (rejoined with one space), headings are bold, table rows are set in a monospace font (one
row per line, kept as a table block), and the running header is oblique and dropped from the page
text. A paragraph break is a vertical gap larger than 1.9 times the font size.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from ainma.ingest.base import BlockKind, ParsedDocument, build_page

PARAGRAPH_GAP = 1.9


@dataclass
class _Fragment:
    y: float
    size: float
    kind: str  # heading | text | table | furniture
    text: str


def _kind_of(font: str) -> str:
    name = font.lower()
    if "courier" in name:
        return "table"
    if "bold" in name:
        return "heading"
    if "oblique" in name or "italic" in name:
        return "furniture"
    return "text"


def _fragments(page: Any) -> list[_Fragment]:
    out: list[_Fragment] = []

    def visit(text: str, cm: list[float], tm: list[float], font: Any, size: float) -> None:
        stripped = text.strip()
        if not stripped:
            return
        base = str(font.get("/BaseFont", "")) if font else ""
        out.append(_Fragment(round(tm[5] + cm[5], 2), float(size), _kind_of(base), stripped))

    page.extract_text(visitor_text=visit)
    return out


def _blocks(fragments: list[_Fragment]) -> list[tuple[BlockKind, str]]:
    blocks: list[tuple[BlockKind, str]] = []
    current: _Fragment | None = None
    kind: str = ""
    lines: list[str] = []

    def flush() -> None:
        if lines and kind in ("heading", "text", "table"):
            sep = "\n" if kind == "table" else " "
            blocks.append((kind, sep.join(lines)))  # type: ignore[arg-type]
        lines.clear()

    for frag in fragments:
        if frag.kind == "furniture":
            continue
        same = (
            current is not None
            and frag.kind == kind
            and frag.size == current.size
            and (current.y - frag.y) <= PARAGRAPH_GAP * frag.size
        )
        if not same:
            flush()
            kind = frag.kind
        lines.append(frag.text)
        current = frag
    flush()
    return blocks


def parse_pdf(source: Path | bytes) -> ParsedDocument:
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    reader = PdfReader(io.BytesIO(data))
    pages = [build_page(_blocks(_fragments(page))) for page in reader.pages]
    return ParsedDocument(tuple(pages))
