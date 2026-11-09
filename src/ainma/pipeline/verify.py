"""Claim verification. The two pure checks come first, the judge check is added below."""

from __future__ import annotations

from ainma.retrieval.quantities import format_number, parse_quantities, quantities_match


def verbatim_span(quote: str, chunk_text: str) -> bool:
    """The quote is a non empty exact substring of the chunk text."""
    return bool(quote) and quote in chunk_text


def numeric_match(claim_text: str, quote: str) -> tuple[bool, str]:
    """Every number of the claim appears in the quote after unit and scale normalisation.

    `EUR 182.4 million`, `182.4m` and a bare table cell `182.4` agree; `1.8 billion` equals
    `1,800 million`; a percent never matches a currency amount; `FY2024` and `2024` are the same
    year. A claim without numbers passes (the judge decides on the words). Binding a number to its
    metric and period inside a quote that holds several is the judge's job, not this check's.
    """
    claim_numbers = parse_quantities(claim_text)
    if not claim_numbers:
        return True, "no number in claim"
    quote_numbers = parse_quantities(quote)
    missing = [
        q for q in claim_numbers if not any(quantities_match(q, other) for other in quote_numbers)
    ]
    if missing:
        return False, "not found in quote: " + ", ".join(q.text for q in missing)
    return True, ", ".join(format_number(q.raw) for q in claim_numbers) + " found in span"
