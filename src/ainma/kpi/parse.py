"""Mock mode KPI parsing: deterministic regex routines over chunk text.

Two readers share one label index. The table reader finds a header line with several periods and
rows whose label is a known KPI wording followed by exactly one number per period. The sentence
reader finds a KPI wording, the next number of a compatible kind and the period that number
belongs to (the nearest period before it, or the one after it when none comes before). Numbers
are normalised: `182.4`, `182,4`, `1,234.5`, `EUR 182.4 million`, `1.2 billion`, `38.5 percent`.

Every candidate carries the offsets of a verbatim quote inside the chunk text, so a citation can
be built by code. This is a reading aid for the offline baseline, not an LLM: it cannot resolve
wordings it does not know, and then the KPI stays `missing`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ainma.kpi.definitions import COUNT, EUR_M, PERCENT, RATIO

NumberKind = Literal["money", "pct", "times", "plain"]

_NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,3}(?:\.\d{3})+,\d+|\d+(?:[.,]\d+)?"
_SCALE = r"million|millions|mn|bn|billion|billions|thousand|k|m"
_NUMBER_RE = re.compile(
    rf"(?P<pre>(?:EUR|€|euros?)\s*)?(?P<neg>[-−])?(?P<num>{_NUMBER})"
    rf"(?:\s*(?P<pct>%|percent\b|per\s+cent\b|pct\b)"
    rf"|\s*(?P<scale>(?:{_SCALE})\b)"
    rf"|\s*(?P<times>x\b|times\b))?",
    re.IGNORECASE,
)
_PERIOD_RE = re.compile(r"\bFY\s?((?:19|20)\d{2}|\d{2})\b|\b((?:19|20)\d{2})\b", re.IGNORECASE)
_TABLE_SCALE_RE = re.compile(
    r"(?:EUR|€)\s*(?P<scale>millions?|mn|m|thousands?|k|billions?|bn)\b"
    r"|\bin\s+(?:EUR\s+)?(?P<in_scale>millions|thousands|billions)\b",
    re.IGNORECASE,
)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])|\n+")
_LEFT_GAP = re.compile(r"\s*(?:of\s+(?:[\w-]+\s+){0,2})?")
_PERIOD_LEAD = re.compile(r"\s*[:=(\-]?\s*")
_PERIOD_TRAIL = re.compile(r"\s*(?:in|for|during|at|of)?\s*", re.IGNORECASE)
_FACTORS = {
    "million": 1.0,
    "millions": 1.0,
    "mn": 1.0,
    "m": 1.0,
    "bn": 1000.0,
    "billion": 1000.0,
    "billions": 1000.0,
    "thousand": 0.001,
    "thousands": 0.001,
    "k": 0.001,
}
_VERIFY_SCALES = (1.0, 1e-3, 1e3, 1e-6, 1e6)


@dataclass(frozen=True)
class Candidate:
    """A value read for one KPI and period. `start:end` is a verbatim quote in the chunk text."""

    kpi_id: str
    period: str
    value: float
    start: int
    end: int
    origin: Literal["table", "sentence"]


@dataclass(frozen=True)
class _Number:
    start: int
    end: int
    kind: NumberKind
    value: float  # normalised to EUR m for money, as written otherwise


def parse_number(token: str) -> float:
    """`182.4`, `182,4`, `1,234.5` and `1.234,5` to a float. A lone dot is always a decimal."""
    token = token.strip()
    if "," in token and "." in token:
        decimal = "," if token.rfind(",") > token.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        token = token.replace(thousands, "").replace(decimal, ".")
    elif "," in token:
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", token):
            token = token.replace(",", "")
        else:
            token = token.replace(",", ".")
    return float(token)


def normalise_period(raw: str) -> str:
    """`FY2024`, `FY 24`, `2024` to `FY2024`."""
    digits = re.sub(r"\D", "", raw)
    year = digits if len(digits) == 4 else f"20{digits}"
    return f"FY{year}"


def _periods_in(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), normalise_period(m.group(0))) for m in _PERIOD_RE.finditer(text)]


def _numbers_in(text: str, periods: Sequence[tuple[int, int, str]]) -> list[_Number]:
    found: list[_Number] = []
    for match in _NUMBER_RE.finditer(text):
        if any(p_start < match.end() and match.start() < p_end for p_start, p_end, _ in periods):
            continue
        value = parse_number(match.group("num"))
        if match.group("neg"):
            value = -value
        scale = (match.group("scale") or "").lower()
        kind: NumberKind
        if match.group("pct"):
            kind = "pct"
        elif match.group("times"):
            kind = "times"
        elif match.group("pre") or scale:
            kind = "money"
            if scale:
                value *= _FACTORS[scale]
            elif abs(value) >= 1e6:
                value /= 1e6
        else:
            kind = "plain"
        found.append(_Number(match.start(), match.end(), kind, value))
    return found


def _compatible(unit: str, number: _Number) -> bool:
    if unit == EUR_M:
        return number.kind == "money"
    if unit == PERCENT:
        return number.kind == "pct"
    if unit == RATIO:
        return number.kind == "times"
    if unit == COUNT:
        return number.kind == "plain" and float(number.value).is_integer()
    return False


class LabelIndex:
    """Recognises KPI wordings in text: whole words, longest wording first, case insensitive."""

    def __init__(self, labels: Mapping[str, Sequence[str]], units: Mapping[str, str]) -> None:
        self.units = dict(units)
        self._by_alias = {
            alias.lower(): kpi for kpi, aliases in labels.items() for alias in aliases
        }
        ordered = sorted(self._by_alias, key=lambda a: (-len(a), a))
        pattern = "|".join(re.escape(alias) for alias in ordered)
        self._regex = re.compile(rf"(?<![\w&'])(?:{pattern})(?![\w])", re.IGNORECASE)

    def find(self, text: str) -> list[tuple[int, int, str]]:
        return [
            (m.start(), m.end(), self._by_alias[m.group(0).lower()])
            for m in self._regex.finditer(text)
        ]

    def exact(self, label: str) -> str | None:
        normalised = re.sub(r"\([^)]*\)", " ", label.lower())
        normalised = re.sub(r"[^a-z&' ]", " ", normalised)
        return self._by_alias.get(re.sub(r"\s+", " ", normalised).strip())


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in _SENTENCE_BREAK.finditer(text):
        spans.append((cursor, match.start()))
        cursor = match.end()
    spans.append((cursor, len(text)))
    return [(s, e) for s, e in spans if e > s]


def _nearest_period(
    periods: Sequence[tuple[int, int, str]], number: _Number
) -> tuple[int, int, str] | None:
    before = [p for p in periods if p[1] <= number.start]
    if before:
        return before[-1]
    after = [p for p in periods if p[0] >= number.end]
    return after[0] if after else None


def _introduced_period(
    text: str, periods: Sequence[tuple[int, int, str]], number: _Number
) -> tuple[int, int, str] | None:
    """The period written right before (`FY2023: EUR 168.0m`) or right after (`168.0 in FY2023`)."""
    before = [p for p in periods if p[1] <= number.start]
    if before and _PERIOD_LEAD.fullmatch(text[before[-1][1] : number.start]):
        return before[-1]
    after = [p for p in periods if p[0] >= number.end]
    if after and _PERIOD_TRAIL.fullmatch(text[number.end : after[0][0]]):
        return after[0]
    return None


def _sentence_candidates(text: str, offset: int, index: LabelIndex) -> list[Candidate]:
    aliases = index.find(text)
    periods = _periods_in(text)
    if not aliases or not periods:
        return []
    numbers = _numbers_in(text, periods)
    out: list[Candidate] = []
    for position, (a_start, a_end, kpi_id) in enumerate(aliases):
        unit = index.units[kpi_id]
        window_end = aliases[position + 1][0] if position + 1 < len(aliases) else len(text)
        forward = [
            n for n in numbers if a_end <= n.start and n.end <= window_end and _compatible(unit, n)
        ]
        accepted: list[tuple[_Number, tuple[int, int, str]]] = []
        if forward:
            first = forward[0]
            period = _nearest_period(periods, first)
            if period is not None:
                accepted.append((first, period))
            for extra in forward[1:]:
                introduced = _introduced_period(text, periods, extra)
                if introduced is not None and all(introduced is not used for _, used in accepted):
                    accepted.append((extra, introduced))
        else:
            left = [n for n in numbers if n.end <= a_start and _compatible(unit, n)]
            if left and _LEFT_GAP.fullmatch(text[left[-1].end : a_start]):
                period = _nearest_period(periods, left[-1])
                if period is not None:
                    accepted.append((left[-1], period))
        for number, (p_start, p_end, period_name) in accepted:
            start = min(a_start, number.start, p_start)
            end = max(a_end, number.end, p_end)
            out.append(
                Candidate(
                    kpi_id, period_name, number.value, offset + start, offset + end, "sentence"
                )
            )
    return out


def _table_scale(text: str) -> float | None:
    match = _TABLE_SCALE_RE.search(text)
    if match is None:
        return None
    raw = (match.group("scale") or match.group("in_scale")).lower().rstrip("s")
    return _FACTORS.get(raw)


def _table_candidates(text: str, index: LabelIndex) -> list[Candidate]:
    scale = _table_scale(text)
    out: list[Candidate] = []
    columns: list[str] = []
    cursor = 0
    for line in text.split("\n"):
        start = cursor
        cursor += len(line) + 1
        if not line.strip():
            continue
        periods = _periods_in(line)
        residue = _NUMBER_RE.sub(" ", _PERIOD_RE.sub(" ", line))
        if len(periods) >= 2 and not re.search(r"\d", residue):
            columns = [name for _, _, name in periods]
            continue
        first = _NUMBER_RE.search(line)
        if not columns or first is None:
            continue
        kpi_id = index.exact(line[: first.start()])
        if kpi_id is None:
            continue
        cells = [parse_number(m.group("num")) for m in _NUMBER_RE.finditer(line, first.start())]
        negatives = [
            line[m.start() - 1 : m.start()] in "-−" or line[m.start() - 1 : m.start()] == "("
            for m in _NUMBER_RE.finditer(line, first.start())
        ]
        if len(cells) != len(columns):
            continue
        quote_start = start + (len(line) - len(line.lstrip()))
        quote_end = start + len(line.rstrip())
        unit = index.units[kpi_id]
        for column, value, negative in zip(columns, cells, negatives, strict=True):
            signed = -value if negative else value
            if unit == EUR_M:
                signed = (
                    signed * scale
                    if scale is not None
                    else (signed / 1e6 if abs(signed) >= 1e6 else signed)
                )
            out.append(Candidate(kpi_id, column, signed, quote_start, quote_end, "table"))
    return out


def parse_chunk(text: str, index: LabelIndex) -> list[Candidate]:
    """All candidates in a chunk: table rows first, then sentences, each in text order."""
    out = _table_candidates(text, index)
    for start, end in _sentence_spans(text):
        out.extend(_sentence_candidates(text[start:end], start, index))
    return out


def value_in_quote(value: float, quote: str) -> bool:
    """The value appears in the quote after normalisation of separators, scale words and percent.

    `182.4` is found in `EUR 182.4 million`, `182,4`, `EUR 0.1824 billion` and in a table row of
    raw numbers whose header scale is not part of the quote (factors of 1e3 and 1e6 are tolerated
    for that reason). Percentages match their written number. Years are never read as values.
    """
    numbers = _numbers_in(quote, _periods_in(quote))
    return any(
        abs(number.value * scale - value) <= 1e-9 * max(1.0, abs(value))
        for number in numbers
        for scale in _VERIFY_SCALES
    )
