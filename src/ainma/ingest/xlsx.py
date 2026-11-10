"""XLSX parser. One page per worksheet: a heading (the sheet name) and one table block.

Numeric cells are rendered with the cell number format (`0.0` prints one decimal), so the text
is identical to what the generator planted.
"""

from __future__ import annotations

import io
from pathlib import Path

from openpyxl import load_workbook  # type: ignore[import-untyped,unused-ignore]

from ainma.ingest.base import BlockKind, ParsedDocument, build_page, fmt_cell, row_text


def _cell_text(value: object, number_format: str) -> str:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return fmt_cell(value)
    if isinstance(value, int | float):
        if number_format == "0.0":
            return f"{float(value):.1f}"
        if float(value).is_integer():
            return str(int(value))
        return fmt_cell(float(value))
    return fmt_cell(value)


def parse_xlsx(source: Path | bytes) -> ParsedDocument:
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    workbook = load_workbook(io.BytesIO(data), data_only=True)
    pages = []
    for sheet in workbook.worksheets:
        rows: list[str] = []
        for row in sheet.iter_rows():
            text = row_text([_cell_text(c.value, c.number_format) for c in row])
            if text:
                rows.append(text)
        items: list[tuple[BlockKind, str]] = [("heading", sheet.title)]
        if rows:
            items.append(("table", "\n".join(rows)))
        pages.append(build_page(items))
    if not pages:
        pages.append(build_page([]))
    return ParsedDocument(tuple(pages))
