"""Number extraction and matching shared by the citation and KPI metrics.

The checks here are deliberately independent of the pipeline's own verifier, so that the harness
does not grade the system with the system's code.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# A number is not glued to a letter, digit or dot on its left (so "FY2024" and "Q3" are not
# numbers), and may carry a unit suffix on its right ("182.4m", "38.5%").
_NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*(?!\d)")
_THOUSANDS = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_DECIMAL_COMMA = re.compile(r"^\d+,\d{1,2}$")

_SCALES = (1.0, 1e3, 1e6, 1e-3, 1e-6)


def _parse(token: str) -> float | None:
    if _THOUSANDS.match(token):
        return float(token.replace(",", ""))
    if _DECIMAL_COMMA.match(token):
        return float(token.replace(",", "."))
    try:
        return float(token)
    except ValueError:
        return None


def extract_numbers(text: str) -> list[float]:
    """Every number of `text`, in order. Thousands separators and decimal commas are normalised."""
    values: list[float] = []
    for match in _NUMBER.finditer(text):
        token = match.group(0).rstrip(".,")
        parsed = _parse(token)
        if parsed is not None:
            values.append(parsed)
    return values


def close(a: float, b: float, rel_tol: float) -> bool:
    return abs(a - b) <= rel_tol * max(abs(b), 1e-12)


def value_in_text(value: float, text: str, *, rel_tol: float = 1e-6) -> bool:
    """The normalised `value` appears in `text` (same scale)."""
    return any(close(found, value, rel_tol) for found in extract_numbers(text))


def value_in_text_any_scale(value: float, text: str, *, rel_tol: float = 5e-3) -> bool:
    """Like `value_in_text` but accepts powers of 1000 (EUR 182.4 million versus 182,400)."""
    found = extract_numbers(text)
    return any(close(f * scale, value, rel_tol) for f in found for scale in _SCALES)


def numbers_covered(claim: str, quotes: Sequence[str]) -> bool:
    """Every number of `claim` appears in the union of `quotes`."""
    pool = [n for quote in quotes for n in extract_numbers(quote)]
    return all(any(close(p, n, 1e-6) for p in pool) for n in extract_numbers(claim))
