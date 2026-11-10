"""Deterministic file writers (PDF, DOCX, XLSX, TXT) for a `DocSpec`.

Determinism: fixed creation dates, core fonts only, ASCII text only, and a rewrite of the zip
containers (fixed entry timestamps and core properties) so the same spec gives the same bytes.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import UTC, datetime

from docx import Document
from docx.shared import Pt
from fpdf import FPDF
from openpyxl import Workbook

from ainma.ingest.base import row_text
from ainma.synth.docspec import Block, DocSpec, Heading, PageBreak, Para, Table

FIXED_DATETIME = datetime(2025, 1, 1, 0, 0, 0)
_FIXED_ZIP_TIME = (2025, 1, 1, 0, 0, 0)
_PDF_LEFT = 20.0
_PDF_WIDTH = 170.0
_PDF_TOP = 24.0
_PDF_BOTTOM = 277.0
_LINE = 5.0
_GAP = 3.0
_MARK = "SYNTHETIC DOCUMENT, fictional data"
_COURIER_MAX_CHARS = 100


def _check_ascii(text: str, where: str) -> None:
    if not text.isascii():
        raise ValueError(f"non ASCII text in {where}: {text[:60]!r}")
    if "  " in text or "\n" in text:
        raise ValueError(f"double space or newline in {where}: {text[:60]!r}")


def normalize_zip(data: bytes) -> bytes:
    """Rewrite a zip container with fixed timestamps and fixed core property dates."""
    out = io.BytesIO()
    stamp = FIXED_DATETIME.strftime("%Y-%m-%dT%H:%M:%SZ")
    with (
        zipfile.ZipFile(io.BytesIO(data)) as src,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for info in src.infolist():
            payload = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                text = payload.decode("utf-8")
                text = re.sub(
                    r"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)",
                    rf"\g<1>{stamp}\g<2>",
                    text,
                )
                payload = text.encode("utf-8")
            entry = zipfile.ZipInfo(info.filename, date_time=_FIXED_ZIP_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o600 << 16
            entry.create_system = 3
            dst.writestr(entry, payload)
    return out.getvalue()


# ---- PDF ----------------------------------------------------------------------------------


class _Pdf(FPDF):
    pass


def _wrap(pdf: FPDF, text: str, width: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        trial = word if not current else f"{current} {word}"
        if current and pdf.get_string_width(trial) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def write_pdf(spec: DocSpec) -> bytes:
    pdf = _Pdf(format="A4", unit="mm")
    pdf.set_auto_page_break(False)
    pdf.set_creation_date(FIXED_DATETIME.replace(tzinfo=UTC))
    pdf.set_title(spec.title)
    pdf.set_author("Synthetic generator")
    pdf.set_creator("ainma.synth")
    pdf.set_margins(_PDF_LEFT, _PDF_TOP, _PDF_LEFT)
    header = f"{_MARK} | {spec.title}"[:110]
    _check_ascii(header, f"{spec.id} header")
    state = {"y": _PDF_TOP}

    def new_page() -> None:
        pdf.add_page()
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_xy(_PDF_LEFT, 12)
        pdf.cell(_PDF_WIDTH, 4, header, new_x="LMARGIN", new_y="NEXT")
        state["y"] = _PDF_TOP

    def ensure(height: float) -> None:
        if state["y"] + height > _PDF_BOTTOM:
            new_page()

    def put_lines(lines: list[str], height: float) -> None:
        for line in lines:
            pdf.set_xy(_PDF_LEFT, state["y"])
            pdf.cell(_PDF_WIDTH, height, line)
            state["y"] += height
        state["y"] += _GAP

    new_page()
    blocks: list[Block] = spec.blocks
    for index, block in enumerate(blocks):
        if isinstance(block, PageBreak):
            if state["y"] > _PDF_TOP:
                new_page()
        elif isinstance(block, Heading):
            _check_ascii(block.text, f"{spec.id} heading")
            size = {1: 14, 2: 12}.get(block.level, 11)
            pdf.set_font("Helvetica", "B", size)
            lines = _wrap(pdf, block.text, _PDF_WIDTH)
            height = size * 0.5
            ensure(height * len(lines) + _GAP + 18)
            put_lines(lines, height)
        elif isinstance(block, Para):
            _check_ascii(block.text, f"{spec.id} paragraph")
            pdf.set_font("Helvetica", "", 10)
            lines = _wrap(pdf, block.text, _PDF_WIDTH)
            need = _LINE * len(lines) + _GAP
            if need > _PDF_BOTTOM - _PDF_TOP:
                raise ValueError(f"{spec.id}: paragraph longer than a page")
            ensure(need)
            put_lines(lines, _LINE)
        elif isinstance(block, Table):
            pdf.set_font("Courier", "", 8)
            texts = block.row_texts()
            for text in texts:
                _check_ascii(text, f"{spec.id} table row")
                if len(text) > _COURIER_MAX_CHARS:
                    raise ValueError(f"{spec.id}: table row too wide: {text!r}")
            ensure(_LINE * min(len(texts), 6) + _GAP)
            for text in texts:
                ensure(_LINE)
                pdf.set_font("Courier", "", 8)
                pdf.set_xy(_PDF_LEFT, state["y"])
                pdf.cell(_PDF_WIDTH, _LINE, text)
                state["y"] += _LINE
            state["y"] += _GAP
        _ = index
    return bytes(pdf.output())


# ---- DOCX ---------------------------------------------------------------------------------


def write_docx(spec: DocSpec) -> bytes:
    document = Document()
    props = document.core_properties
    props.author = "Synthetic generator"
    props.last_modified_by = "Synthetic generator"
    props.title = spec.title
    props.created = FIXED_DATETIME
    props.modified = FIXED_DATETIME
    props.revision = 1
    props.comments = ""
    normal = document.styles["Normal"]
    normal.font.size = Pt(10)  # type: ignore[attr-defined]
    for block in spec.blocks:
        if isinstance(block, Heading):
            _check_ascii(block.text, f"{spec.id} heading")
            document.add_heading(block.text, level=min(max(block.level, 1), 3))
        elif isinstance(block, Para):
            _check_ascii(block.text, f"{spec.id} paragraph")
            document.add_paragraph(block.text)
        elif isinstance(block, Table):
            width = max(len(r) for r in block.rows)
            table = document.add_table(rows=len(block.rows), cols=width)
            table.style = "Table Grid"
            for r_index, row in enumerate(block.rows):
                for c_index in range(width):
                    value = row[c_index] if c_index < len(row) else ""
                    texts = row_text([value]) if value != "" else ""
                    table.cell(r_index, c_index).text = texts
        elif isinstance(block, PageBreak):
            document.add_page_break()
    buffer = io.BytesIO()
    document.save(buffer)
    return normalize_zip(buffer.getvalue())


# ---- XLSX ---------------------------------------------------------------------------------


def write_xlsx(spec: DocSpec) -> bytes:
    """Sheets are described as a Heading (sheet name) followed by a Table."""
    workbook = Workbook()
    workbook.remove(workbook.active)  # type: ignore[arg-type]
    props = workbook.properties
    props.creator = "Synthetic generator"
    props.lastModifiedBy = "Synthetic generator"
    props.title = spec.title
    props.created = FIXED_DATETIME
    props.modified = FIXED_DATETIME
    pending: str | None = None
    for block in spec.blocks:
        if isinstance(block, Heading):
            pending = block.text
        elif isinstance(block, Table):
            if pending is None:
                raise ValueError(f"{spec.id}: xlsx table without a sheet name")
            sheet = workbook.create_sheet(title=pending)
            for row in block.rows:
                sheet.append(list(row))
            for cells in sheet.iter_rows():
                for cell in cells:
                    if isinstance(cell.value, float):
                        cell.number_format = "0.0"
                    elif isinstance(cell.value, int) and not isinstance(cell.value, bool):
                        cell.number_format = "0"
            pending = None
    buffer = io.BytesIO()
    workbook.save(buffer)
    return normalize_zip(buffer.getvalue())


# ---- TXT ----------------------------------------------------------------------------------


def write_txt(spec: DocSpec) -> bytes:
    pages: list[list[str]] = [[]]
    for block in spec.blocks:
        if isinstance(block, Heading):
            _check_ascii(block.text, f"{spec.id} heading")
            pages[-1].append(f"# {block.text}")
        elif isinstance(block, Para):
            _check_ascii(block.text, f"{spec.id} paragraph")
            pages[-1].append(block.text)
        elif isinstance(block, Table):
            for text in block.row_texts():
                _check_ascii(text, f"{spec.id} table row")
            pages[-1].append("\n".join(block.row_texts()))
        elif isinstance(block, PageBreak):
            pages.append([])
    text = "\f".join("\n\n".join(p) for p in pages if p) + "\n"
    return text.encode("utf-8")


def render(spec: DocSpec) -> bytes:
    if spec.fmt == "pdf":
        return write_pdf(spec)
    if spec.fmt == "docx":
        return write_docx(spec)
    if spec.fmt == "xlsx":
        return write_xlsx(spec)
    return write_txt(spec)
