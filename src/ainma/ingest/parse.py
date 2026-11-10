"""Dispatch by file extension."""

from __future__ import annotations

from pathlib import Path

from ainma.ingest.base import ParsedDocument
from ainma.ingest.docx import parse_docx
from ainma.ingest.pdf import parse_pdf
from ainma.ingest.text import parse_text
from ainma.ingest.xlsx import parse_xlsx


def parse_file(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix == ".docx":
        return parse_docx(path)
    if suffix == ".xlsx":
        return parse_xlsx(path)
    if suffix == ".txt":
        return parse_text(path)
    raise ValueError(f"unsupported document format: {path.name}")
