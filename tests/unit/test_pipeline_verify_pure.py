from __future__ import annotations

import pytest

from ainma.pipeline.verify import numeric_match, verbatim_span
from ainma.retrieval.lexicon import detect_metrics, detect_periods, previous_period
from ainma.retrieval.quantities import extract_facts_rules, parse_quantities, quantities_match
from ainma.retrieval.text import sentence_spans, tokenize

CHUNK = "Net revenue for FY2024 reached EUR 182.4 million (FY2023: EUR 168.0 million)."


def test_verbatim_span_is_exact_substring() -> None:
    assert verbatim_span("EUR 182.4 million", CHUNK)
    assert not verbatim_span("EUR 182.5 million", CHUNK)
    assert not verbatim_span("", CHUNK)
    assert not verbatim_span("net revenue", CHUNK)  # case sensitive: verbatim means verbatim


@pytest.mark.parametrize(
    ("claim", "quote", "passed"),
    [
        ("FY2024 revenue is EUR 182.4 million", CHUNK, True),
        ("Revenue was 182.4m in 2024", CHUNK, True),  # scale word and year form differ
        ("Revenue was 182.4", CHUNK, True),  # bare number against EUR 182.4 million
        ("Revenue was EUR 190.0 million in FY2024", CHUNK, False),  # altered number
        (
            "Revenue was EUR 182.4 million in FY2023",
            "Net revenue for FY2024 was EUR 182.4 million",
            False,
        ),
        ("Fund size is EUR 1.8 billion", "total commitments of EUR 1,800 million", True),
        ("Gross margin is 38.5%", "Gross margin was 38.5 percent in FY2024.", True),
        ("Gross margin is 38.5%", "Revenue was EUR 38.5 million", False),  # percent vs currency
        ("Table cell", "Revenue | 182.4", True),  # no number in the claim
        ("Customers", "no numbers here", True),
    ],
)
def test_numeric_match_normalises_units_and_scales(claim: str, quote: str, passed: bool) -> None:
    ok, detail = numeric_match(claim, quote)
    assert ok is passed
    assert detail


def test_numeric_match_detail_names_the_missing_number() -> None:
    ok, detail = numeric_match("Revenue was EUR 190.0 million", CHUNK)
    assert not ok and "190.0" in detail
    ok, detail = numeric_match("Revenue was EUR 182.4 million", CHUNK)
    assert ok and detail == "182.4 found in span"


def test_quantity_parsing_by_hand() -> None:
    quantities = parse_quantities("EUR 1.8 billion, 5,200 staff, 12.5%, FY24, 2x")
    assert [(q.kind, q.value) for q in quantities] == [
        ("money", 1.8e9),
        ("number", 5200.0),
        ("percent", 12.5),
        ("year", 2024.0),
        ("multiple", 2.0),
    ]
    a, b = parse_quantities("EUR 182.4 million")[0], parse_quantities("182.4")[0]
    assert quantities_match(a, b)
    assert not quantities_match(parse_quantities("12%")[0], parse_quantities("EUR 12 million")[0])


def test_months_and_glued_digits_are_not_quantities() -> None:
    assert [q.kind for q in parse_quantities("in 3 months, H1 and Q3")] == ["number"]


def test_periods_and_metrics() -> None:
    text = "Net revenue FY24, fiscal 2023, H1 2024 and Q3 FY2025; signed on 14 March 2022."
    assert detect_periods(text) == ["FY2024", "FY2023", "H1 2024", "Q3 2025"]
    assert previous_period("FY2024") == "FY2023" and previous_period("H1 2024") is None
    assert detect_metrics("Gross profit margin and EBITDA, then EBIT and the largest customer") == [
        "gross_margin",
        "ebitda",
        "operating_income",
        "top_customer_share",
    ]


def test_rule_based_facts_bind_metric_period_and_unit() -> None:
    facts = extract_facts_rules(CHUNK + " Gross margin was 38.5 percent in FY2024.")
    keyed = {(f.metric, f.period): (f.value, f.unit) for f in facts}
    assert keyed == {
        ("revenue", "FY2024"): (182.4, "EUR m"),
        ("revenue", "FY2023"): (168.0, "EUR m"),
        ("gross_margin", "FY2024"): (38.5, "%"),
    }
    text = "Revenue grew from EUR 168.0 million in FY2023 to EUR 182.4 million in FY2024."
    assert {(f.period, f.value) for f in extract_facts_rules(text)} == {
        ("FY2023", 168.0),
        ("FY2024", 182.4),
    }


def test_tokenizer_and_sentences() -> None:
    assert tokenize("What was Aurora's FY2024 revenues in 1,234.5?") == [
        "aurora",
        "fy2024",
        "2024",
        "revenue",
        "1234.5",
    ]
    text = "First sentence.  Second one, 3.5 percent.\n\nThird"
    assert [text[a:b] for a, b in sentence_spans(text)] == [
        "First sentence.",
        "Second one, 3.5 percent.",
        "Third",
    ]


def test_year_ended_phrase_is_a_period_and_adjusted_ebitda_is_its_own_metric() -> None:
    assert detect_periods("Sales totalled EUR 5 million for the year ended 31 December 2024.") == [
        "FY2024"
    ]
    assert detect_periods("signed on 31 December 2024") == []
    assert detect_metrics("adjusted EBITDA and EBITDA") == ["adjusted_ebitda", "ebitda"]
