"""Parsers and chunker: page text first, chunks are exact slices (store invariant D04)."""

from __future__ import annotations

from datetime import date

import pytest

from ainma.contracts import DocType, DocumentMeta
from ainma.ingest.base import ParsedDocument, fmt_cell, paginate, row_text
from ainma.ingest.chunker import chunk_document
from ainma.ingest.docx import parse_docx
from ainma.ingest.pdf import parse_pdf
from ainma.ingest.text import parse_text
from ainma.ingest.xlsx import parse_xlsx
from ainma.synth.docspec import DocSpec, Part
from ainma.synth.writers import render

SENTENCE = "Net revenue for FY2024 reached EUR 182.4 million (FY2023: EUR 168.0 million)."


def _spec(fmt: str) -> DocSpec:
    spec = DocSpec(
        id="doc_t",
        folder="x",
        fmt=fmt,  # type: ignore[arg-type]
        title="Test document",
        doc_type=DocType.DEAL_DOCUMENT,
        published_on=date(2025, 1, 1),
    )
    if fmt == "xlsx":
        spec.heading("Income statement")
        spec.table(
            [["EUR m", "FY2023", "FY2024"], ["Revenue", 168.0, 182.4], ["Headcount", 1200, 1240]]
        )
        return spec
    spec.heading("1. Financial overview")
    spec.para(
        "Intro sentence is here.", Part(SENTENCE, ("f1",)), " ".join(["More words here."] * 40)
    )
    spec.para("Second paragraph.")
    spec.table([["Metric", "FY2023", "FY2024"], ["Revenue", 168.0, 182.4]], {1: ("f2",)})
    spec.page_break()
    spec.heading("2. Next")
    spec.para("Another page text.")
    return spec


def _meta(parsed: ParsedDocument) -> DocumentMeta:
    return DocumentMeta(
        id="doc_t", title="t", doc_type=DocType.DEAL_DOCUMENT, n_pages=len(parsed.pages), sha256="x"
    )


@pytest.mark.parametrize(
    ("fmt", "parser"),
    [("pdf", parse_pdf), ("docx", parse_docx), ("txt", parse_text)],
)
def test_text_formats_agree_on_page_text(fmt: str, parser: object) -> None:
    parsed = parser(render(_spec(fmt)))  # type: ignore[operator]
    assert len(parsed.pages) == 2
    page1 = parsed.pages[0].text
    assert SENTENCE in page1  # wrapped lines are rejoined, quote is verbatim
    assert "Revenue | 168.0 | 182.4" in page1
    kinds = [b.kind for b in parsed.pages[0].blocks]
    assert kinds[0] == "heading" and kinds[-1] == "table"
    assert parsed.pages[1].text.endswith("Another page text.")


@pytest.mark.parametrize(
    ("fmt", "parser"),
    [("pdf", parse_pdf), ("docx", parse_docx), ("txt", parse_text), ("xlsx", parse_xlsx)],
)
def test_chunks_are_exact_page_slices(fmt: str, parser: object) -> None:
    parsed = parser(render(_spec(fmt)))  # type: ignore[operator]
    chunks = chunk_document(_meta(parsed), parsed)
    assert chunks
    for chunk in chunks:
        page = parsed.pages[chunk.page - 1].text
        assert page[chunk.char_start : chunk.char_end] == chunk.text
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids)) and ids[0] == "ch_t_p1_01"
    table_chunks = [c for c in chunks if c.kind == "table"]
    assert table_chunks and all(" | " in c.text for c in table_chunks)


def test_xlsx_one_page_per_sheet_with_canonical_numbers() -> None:
    parsed = parse_xlsx(render(_spec("xlsx")))
    assert len(parsed.pages) == 1
    assert parsed.pages[0].text == (
        "Income statement\n\nEUR m | FY2023 | FY2024\nRevenue | 168.0 | 182.4\n"
        "Headcount | 1200 | 1240"
    )


def test_pdf_header_is_dropped_but_synthetic_mark_is_in_the_file() -> None:
    data = render(_spec("pdf"))
    assert "SYNTHETIC" not in parse_pdf(data).pages[0].text
    assert b"Helvetica-Oblique" in data


def test_long_paragraph_is_cut_at_sentence_boundaries() -> None:
    text = " ".join(f"Sentence number {i} says something useful here." for i in range(60))
    parsed = parse_text(text)
    chunks = chunk_document(_meta(parsed), parsed, max_chars=300)
    assert len(chunks) > 5
    assert all(c.text.endswith(".") for c in chunks)
    assert all(len(c.text) <= 300 for c in chunks)


def test_table_rows_are_never_split() -> None:
    rows = "\n".join(f"Row {i} | {i}.0 | {i + 1}.0" for i in range(80))
    parsed = parse_text(rows)
    chunks = chunk_document(_meta(parsed), parsed, max_table_chars=200)
    assert len(chunks) > 3
    for chunk in chunks:
        assert all(line.count(" | ") == 2 for line in chunk.text.split("\n"))


def test_pagination_limit_and_explicit_breaks() -> None:
    items = [("text", "a" * 30), ("text", "b" * 30), None, ("text", "c" * 30)]
    pages = paginate(items, limit=50)
    assert [p.text.count("\n\n") for p in pages] == [0, 0, 0]
    assert len(paginate([])) == 1


def test_cell_rendering_is_canonical() -> None:
    assert fmt_cell(168.0) == "168.0" and fmt_cell(1240) == "1240" and fmt_cell(None) == ""
    assert row_text(["Revenue", 168.0, 182.4, "", ""]) == "Revenue | 168.0 | 182.4"
