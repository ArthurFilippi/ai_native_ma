"""Plain text parser.

Pages are separated by a form feed. Blocks are separated by blank lines. A block is a heading
when it is one line starting with `# ` and a table when it has at least two lines, all containing
` | `. Line endings are normalised and trailing blanks stripped, so page text is canonical.
"""

from __future__ import annotations

import re
from pathlib import Path

from ainma.ingest.base import CELL_SEP, BlockKind, ParsedDocument, paginate


def _kind(block: str) -> BlockKind:
    lines = block.split("\n")
    if len(lines) == 1 and block.startswith("# "):
        return "heading"
    if len(lines) >= 2 and all(CELL_SEP in line for line in lines):
        return "table"
    return "text"


def parse_text(source: Path | bytes | str) -> ParsedDocument:
    if isinstance(source, str):
        raw = source
    elif isinstance(source, bytes):
        raw = source.decode("utf-8")
    else:
        raw = Path(source).read_text(encoding="utf-8")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    items: list[tuple[BlockKind, str] | None] = []
    for index, page in enumerate(raw.split("\f")):
        if index:
            items.append(None)
        for block in re.split(r"\n\s*\n", page):
            cleaned = "\n".join(line.rstrip() for line in block.strip("\n").split("\n")).strip()
            if cleaned:
                items.append((_kind(cleaned), cleaned))
    return ParsedDocument(paginate(items))
