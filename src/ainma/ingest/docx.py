"""DOCX parser. Paragraphs and tables in document order.

Logical pages: an explicit page break (a run with `w:br w:type="page"`) closes the page. When a
page grows beyond `PAGE_CHAR_LIMIT` characters it is closed at the next block boundary. Headings
are paragraphs whose style name starts with `Heading` or is `Title`.
"""

from __future__ import annotations

import io
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from ainma.ingest.base import BlockKind, ParsedDocument, paginate, row_text

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _has_page_break(paragraph: Paragraph) -> bool:
    return any(br.get(f"{_W}type") == "page" for br in paragraph._p.iter(f"{_W}br"))


def parse_docx(source: Path | bytes) -> ParsedDocument:
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    document = Document(io.BytesIO(data))
    items: list[tuple[BlockKind, str] | None] = []
    for child in document.element.body.iterchildren():
        if child.tag == f"{_W}p":
            paragraph = Paragraph(child, document)
            style = paragraph.style.name if paragraph.style is not None else ""
            text = paragraph.text.strip()
            if text:
                kind: BlockKind = (
                    "heading" if style.startswith("Heading") or style == "Title" else "text"
                )
                items.append((kind, text))
            if _has_page_break(paragraph):
                items.append(None)
        elif child.tag == f"{_W}tbl":
            table = Table(child, document)
            rows = [row_text([cell.text.strip() for cell in row.cells]) for row in table.rows]
            rows = [r for r in rows if r]
            if rows:
                items.append(("table", "\n".join(rows)))
    return ParsedDocument(paginate(items))
