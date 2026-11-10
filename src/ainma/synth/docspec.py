"""Abstract document description: blocks that the writers render and the planter tracks.

A `Part` is one sentence (or one row quote) and carries the ids of the facts planted in it. The
quote of a fact is the exact text of its part, so the planted span is verbatim by construction
and is located in the parsed page text after the file is written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from ainma.contracts import DocStatus, DocType
from ainma.ingest.base import row_text

Cell = str | int | float


@dataclass(frozen=True)
class Part:
    text: str
    facts: tuple[str, ...] = ()


@dataclass
class Para:
    parts: list[Part]

    @property
    def text(self) -> str:
        return " ".join(p.text.strip() for p in self.parts)


@dataclass
class Heading:
    text: str
    level: int = 1


@dataclass
class Table:
    rows: list[list[Cell]]
    facts: dict[int, tuple[str, ...]] = field(default_factory=dict)  # row index -> fact ids

    def row_texts(self) -> list[str]:
        return [row_text(r) for r in self.rows]


@dataclass
class PageBreak:
    pass


Block = Para | Heading | Table | PageBreak


@dataclass
class DocSpec:
    id: str
    folder: str
    fmt: Literal["pdf", "docx", "xlsx", "txt"]
    title: str
    doc_type: DocType
    published_on: date
    deal_id: str | None = None
    entity_id: str | None = None
    status: DocStatus = DocStatus.CURRENT
    superseded_by: str | None = None
    blocks: list[Block] = field(default_factory=list)

    @property
    def path(self) -> str:
        return f"{self.folder}/{self.id}.{self.fmt}"

    def heading(self, text: str, level: int = 1) -> None:
        self.blocks.append(Heading(text, level))

    def para(self, *parts: str | Part) -> Para:
        converted = [Part(p) if isinstance(p, str) else p for p in parts]
        block = Para(converted)
        self.blocks.append(block)
        return block

    def table(self, rows: list[list[Cell]], facts: dict[int, tuple[str, ...]] | None = None) -> None:
        self.blocks.append(Table(rows, facts or {}))

    def page_break(self) -> None:
        self.blocks.append(PageBreak())

    def events(self) -> list[tuple[str, tuple[str, ...]]]:
        """(quote, fact ids) for every planted part or table row, in document order."""
        out: list[tuple[str, tuple[str, ...]]] = []
        for block in self.blocks:
            if isinstance(block, Para):
                out.extend((p.text, p.facts) for p in block.parts if p.facts)
            elif isinstance(block, Table):
                texts = block.row_texts()
                for index, ids in sorted(block.facts.items()):
                    out.append((texts[index], ids))
        return out
