"""Quantities, unit and scale normalisation, and rule based facts.

A `Quantity` keeps what was written (`raw`) and the absolute value after the scale word
(`value`): `EUR 182.4 million` is raw 182.4, value 182400000. Two quantities match when their
absolute values agree, or when one of them carries no scale word and the raw numbers agree
(so `EUR 182.4 million` matches a bare table cell `182.4`). A percent never matches a currency
amount. Years are matched on their own (`FY2024`, `2024`, `FY24` are the same year).

`extract_facts_rules` is the rule based fact extractor used by the mock `extract_facts` task, by
the corroboration bonus of the source ranker and by the mock judge. Money facts are reported in
millions of the currency when a scale word is present, and as written otherwise (tables are
assumed to be in millions, which is how financial documents are laid out).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from ainma.retrieval.lexicon import (
    METRIC_BY_KEY,
    date_spans,
    find_metrics,
    find_periods,
    find_range_phrases,
)
from ainma.retrieval.text import sentence_spans

QuantityKind = Literal["money", "percent", "number", "year", "multiple"]

_SCALES: dict[str, float] = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mn": 1e6,
    "mm": 1e6,
    "million": 1e6,
    "bn": 1e9,
    "billion": 1e9,
    "trillion": 1e12,
}
_CURRENCIES = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
    "EUR": "EUR",
    "USD": "USD",
    "GBP": "GBP",
    "CHF": "CHF",
}

_NUMBER_RE = re.compile(
    r"""(?<![\w.,])
    (?:(?P<cur_pre>EUR|USD|GBP|CHF|€|\$|£)\s?)?
    (?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    (?:\s?(?P<unit>%|percent\b|per\s?cent\b|pct\b|pp\b|x\b
        |(?:thousand|million|billion|trillion)\b|(?:bn|mn|mm|m|k)(?![A-Za-z])))?
    (?:\s?(?P<cur_post>EUR|USD|GBP|CHF)\b)?
    """,
    re.VERBOSE | re.IGNORECASE,
)
_FY_YEAR_RE = re.compile(r"\bFY\s?'?(\d{4}|\d{2})\b(?!\d)", re.IGNORECASE)


@dataclass(frozen=True)
class Quantity:
    text: str
    start: int
    end: int
    raw: float
    value: float
    kind: QuantityKind
    scale: float = 1.0
    currency: str | None = None


def _classify(num: str, unit: str | None, currency: str | None) -> tuple[QuantityKind, float]:
    unit_l = re.sub(r"\s+", "", (unit or "").lower())
    if unit_l in ("%", "percent", "pct", "pp"):
        return "percent", 1.0
    if unit_l == "x":
        return "multiple", 1.0
    scale = _SCALES.get(unit_l, 1.0)
    if currency:
        return "money", scale
    if "." not in num and "," not in num and not unit_l and 1900 <= int(num) <= 2100:
        return "year", 1.0
    return "number", scale


def parse_quantities(text: str) -> list[Quantity]:
    """Every number of `text` with unit and scale, plus fiscal years (`FY24` is year 2024)."""
    found: list[Quantity] = []
    for m in _NUMBER_RE.finditer(text):
        raw = float(m.group("num").replace(",", ""))
        currency_token = m.group("cur_pre") or m.group("cur_post") or ""
        currency = _CURRENCIES.get(currency_token.upper()) or _CURRENCIES.get(currency_token)
        kind, scale = _classify(m.group("num"), m.group("unit"), currency)
        found.append(
            Quantity(
                m.group(0).strip(), m.start(), m.end(), raw, raw * scale, kind, scale, currency
            )
        )
    for m in _FY_YEAR_RE.finditer(text):
        digits = m.group(1)
        year = float(digits if len(digits) == 4 else f"20{digits}")
        found.append(Quantity(m.group(0), m.start(), m.end(), year, year, "year"))
    return sorted(found, key=lambda q: q.start)


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


def quantities_match(a: Quantity, b: Quantity) -> bool:
    if "year" in (a.kind, b.kind):
        return a.kind == b.kind and _close(a.raw, b.raw)
    if a.kind != b.kind and "number" not in (a.kind, b.kind):
        return False
    if _close(a.value, b.value):
        return True
    return (a.scale == 1.0 or b.scale == 1.0) and _close(a.raw, b.raw)


def format_number(value: float) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


# ---- rule based facts --------------------------------------------------------------------------

STATIC_PERIOD = "static"
"""Period of a metric that describes the entity and not a fiscal period (fund vintage year)."""


@dataclass(frozen=True)
class ExtractedFact:
    metric: str
    period: str | None
    value: float  # money in millions when a scale word is present, else as written
    unit: str  # "EUR m", "%", "count" ...
    label: str  # the quantity as written, e.g. "EUR 182.4 million"
    sentence: str  # the sentence, or the row of a table, that states the fact
    start: int  # offsets of the quantity inside the analysed text
    end: int
    kind: QuantityKind
    sentence_start: int = 0  # offsets of `sentence` inside the analysed text
    from_table: bool = False


def _compatible(metric_kind: str, quantity: Quantity) -> bool:
    if metric_kind == "year":
        return quantity.kind == "year"
    if quantity.kind == "year":
        return False
    if metric_kind == "money":
        return quantity.kind in ("money", "number")
    if metric_kind == "percent":
        return quantity.kind == "percent"
    if metric_kind == "multiple":
        return quantity.kind == "multiple"
    return quantity.kind == "number"  # count and duration


def _reported(quantity: Quantity) -> tuple[float, str]:
    if quantity.kind == "percent":
        return quantity.raw, "%"
    if quantity.kind == "multiple":
        return quantity.raw, "x"
    if quantity.kind == "year":
        return quantity.raw, "year"
    if quantity.kind == "money" or quantity.scale != 1.0:
        currency = quantity.currency or "EUR"
        if quantity.scale != 1.0:
            return quantity.value / 1e6, f"{currency} m"
        return quantity.raw, f"{currency} m"
    return quantity.raw, "count"


def _sentence_fact(
    metric: str,
    period: str | None,
    quantity: Quantity,
    sentence: str,
    start: int,
) -> ExtractedFact:
    value, unit = _reported(quantity)
    if METRIC_BY_KEY[metric].static:
        period = STATIC_PERIOD
    return ExtractedFact(
        metric=metric,
        period=period,
        value=value,
        unit=unit,
        label=quantity.text,
        sentence=sentence,
        start=start + quantity.start,
        end=start + quantity.end,
        kind=quantity.kind,
        sentence_start=start,
    )


def extract_facts_rules(text: str) -> list[ExtractedFact]:
    """Facts `(metric, period, value)` found sentence by sentence, plus the cells of tables.

    A quantity takes the nearest compatible metric before it (else the nearest after it). Its
    period is the nearest period by distance (ties prefer the one after); a period followed by a
    colon, as in `(FY2023: EUR 168.0 million)`, only binds to the quantity after it. Metrics of a
    static kind (fund vintage, process length) carry the period `static`. A range phrase (`equity
    tickets of EUR 40 million to EUR 150 million`) gives a minimum and a maximum. Table rows give
    one fact per column whose header names a period.
    """
    facts: list[ExtractedFact] = []
    for start, end in sentence_spans(text):
        sentence = text[start:end]
        if "|" in sentence:
            continue  # table rows are read by `_table_facts`
        facts.extend(_facts_of_sentence(sentence, start))
    facts.extend(_table_facts(text))
    facts.sort(key=lambda f: f.start)
    return facts


def _facts_of_sentence(sentence: str, start: int) -> list[ExtractedFact]:
    metrics = find_metrics(sentence)
    periods = find_periods(sentence)
    dates = date_spans(sentence)
    quantities = [
        q
        for q in parse_quantities(sentence)
        if not any(a <= q.start and q.end <= b for a, b in dates)
        or (q.kind == "year" and not any(a <= q.start and q.end <= b for a, b in dates))
    ]
    facts: list[ExtractedFact] = []
    ranges = find_range_phrases(sentence)
    if ranges:
        (low_key, high_key), _, _ = ranges[0]
        money = [q for q in quantities if q.kind == "money"]
        if len(money) >= 2:
            facts.append(_sentence_fact(low_key, None, money[0], sentence, start))
            facts.append(_sentence_fact(high_key, None, money[1], sentence, start))
            return facts
    for quantity in quantities:
        options = [m for m in metrics if _compatible(METRIC_BY_KEY[m[0]].kind, quantity)]
        if not options:
            continue
        before = [m for m in options if m[2] <= quantity.start]
        metric = max(before, key=lambda m: m[2]) if before else min(options, key=lambda m: m[1])
        period = _nearest_period(sentence, periods, quantity)
        facts.append(_sentence_fact(metric[0], period, quantity, sentence, start))
    return facts


def _nearest_period(
    sentence: str, periods: list[tuple[str, int, int]], quantity: Quantity
) -> str | None:
    best: tuple[int, int, str] | None = None
    for label, p_start, p_end in periods:
        colon = sentence[p_end:].lstrip(" ").startswith(":")
        if p_end <= quantity.start:
            gap, side = quantity.start - p_end, 1
            if colon and gap > 3:
                continue
        else:
            if colon:
                continue
            gap, side = p_start - quantity.end, 0
        candidate = (gap, side, label)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return best[2] if best else None


# ---- tables ------------------------------------------------------------------------------------

_CELL_NUMBER = re.compile(r"^\(?-?\d[\d,]*(?:\.\d+)?\)?%?$")


def _row_cells(line: str) -> list[tuple[str, int, int]]:
    """(cell text, start, end) of the cells of a row `a | b | c`, offsets inside `line`."""
    cells: list[tuple[str, int, int]] = []
    position = 0
    for raw in line.split("|"):
        stripped = raw.strip()
        offset = position + (len(raw) - len(raw.lstrip()))
        cells.append((stripped, offset, offset + len(stripped)))
        position += len(raw) + 1
    return cells


def _table_facts(text: str) -> list[ExtractedFact]:
    """Cells of rows `Label | v1 | v2 ...` under a header row that names periods. The unit is the
    first header cell (`EUR m`); a row whose label is not a known metric is skipped."""
    facts: list[ExtractedFact] = []
    offset = 0
    header: list[str | None] | None = None
    currency = "EUR"
    for line in text.split("\n"):
        line_start = offset
        offset += len(line) + 1
        if line.count("|") < 2:
            continue
        cells = _row_cells(line)
        periods = [_cell_period(c[0]) for c in cells[1:]]
        if sum(p is not None for p in periods) >= 2:
            header = periods
            first = cells[0][0].upper()
            currency = next((c for c in ("EUR", "USD", "GBP", "CHF") if c in first), "EUR")
            continue
        if header is None:
            continue
        label_cell = cells[0][0]
        found = find_metrics(label_cell)
        if not found or found[0][1] != 0 or found[0][2] != len(label_cell):
            continue
        metric = found[0][0]
        kind = METRIC_BY_KEY[metric].kind
        if kind in ("year", "multiple", "duration"):
            continue
        for index, (cell, c_start, c_end) in enumerate(cells[1:]):
            period = header[index] if index < len(header) else None
            if period is None or not _CELL_NUMBER.match(cell):
                continue
            raw = float(cell.strip("()%").replace(",", ""))
            if cell.startswith("(") and cell.endswith(")"):
                raw = -raw
            if kind == "percent" or cell.endswith("%"):
                value, unit, qkind = raw, "%", "percent"
            elif kind == "money":
                value, unit, qkind = raw, f"{currency} m", "money"
            else:
                value, unit, qkind = raw, "count", "number"
            facts.append(
                ExtractedFact(
                    metric=metric,
                    period=period,
                    value=value,
                    unit=unit,
                    label=cell,
                    sentence=line,
                    start=line_start + c_start,
                    end=line_start + c_end,
                    kind=qkind,  # type: ignore[arg-type]
                    sentence_start=line_start,
                    from_table=True,
                )
            )
    return facts


def _cell_period(cell: str) -> str | None:
    found = find_periods(cell)
    return found[0][0] if len(found) == 1 and found[0][1] == 0 else None
