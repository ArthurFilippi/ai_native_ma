from __future__ import annotations

import pytest

from ainma.kpi.definitions import KPI_LABELS, kpi_definitions
from ainma.kpi.parse import (
    Candidate,
    LabelIndex,
    normalise_period,
    parse_chunk,
    parse_number,
    value_in_quote,
)

INDEX = LabelIndex(KPI_LABELS, {d.id: d.unit for d in kpi_definitions()})


def _read(text: str) -> dict[tuple[str, str], float]:
    return {(c.kpi_id, c.period): c.value for c in parse_chunk(text, INDEX)}


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("182.4", 182.4),
        ("182,4", 182.4),
        ("1,234.5", 1234.5),
        ("1.234,5", 1234.5),
        ("1,250", 1250.0),
        ("38", 38.0),
    ],
)
def test_parse_number(token: str, expected: float) -> None:
    assert parse_number(token) == pytest.approx(expected)


def test_normalise_period() -> None:
    assert [normalise_period(p) for p in ("FY2024", "FY 24", "2024", "fy23")] == [
        "FY2024",
        "FY2024",
        "FY2024",
        "FY2023",
    ]


def test_sentence_with_two_periods_keeps_each_number_on_its_own_period() -> None:
    read = _read("Net revenue for FY2024 reached EUR 182.4 million (FY2023: EUR 168.0 million).")
    assert read == {("revenue", "FY2024"): 182.4, ("revenue", "FY2023"): 168.0}


def test_number_before_the_label_and_period_after() -> None:
    assert _read("Aurora booked roughly EUR 179 million of revenue in 2024.") == {
        ("revenue", "FY2024"): 179.0
    }


def test_percent_wordings_and_separators() -> None:
    read = _read("Gross margin was 38,5 percent in FY2024, against 37.1 percent in FY2023.")
    assert read == {("gross_margin", "FY2024"): 38.5, ("gross_margin", "FY2023"): 37.1}


def test_scale_words_are_normalised_to_eur_millions() -> None:
    assert _read("In FY2024 EBITDA was EUR 0.0315 billion.") == {("ebitda", "FY2024"): 31.5}
    assert _read("In FY2024 EBITDA was EUR 31,500 thousand.") == {("ebitda", "FY2024"): 31.5}
    assert _read("EBITDA of EUR 31,500,000 in FY2024.") == {("ebitda", "FY2024"): 31.5}


def test_a_number_of_the_wrong_kind_is_not_a_value() -> None:
    """Growth in percent is not revenue in euros, a year is not a headcount."""
    assert _read("Revenue growth was 8.6 percent in FY2024.") == {}
    assert _read("Revenue reached EUR 182.4 million in FY2024, up 8.6 percent.") == {
        ("revenue", "FY2024"): 182.4
    }
    assert _read("Aurora employed 1,250 people in FY2024.") == {}
    assert _read("Total headcount reached 1,250 at the end of FY2024.") == {
        ("total_headcount", "FY2024"): 1250.0
    }


def test_longest_wording_wins() -> None:
    read = _read("Operating cash flow was EUR 26.1 million in FY2024.")
    assert read == {("operating_cash_flow", "FY2024"): 26.1}
    read = _read("Net debt stood at EUR 28.6 million at FY2024.")
    assert read == {("net_debt", "FY2024"): 28.6}


def test_two_kpis_in_one_sentence_do_not_swap_numbers() -> None:
    read = _read("In FY2024 revenue was EUR 182.4 million and EBITDA was EUR 31.5 million.")
    assert read == {("revenue", "FY2024"): 182.4, ("ebitda", "FY2024"): 31.5}


def test_sentence_without_a_period_gives_nothing() -> None:
    assert _read("Revenue was EUR 182.4 million.") == {}


def test_pipe_table_maps_each_column_to_its_period() -> None:
    text = (
        "Consolidated income statement (EUR m)\n"
        "Line item | FY2020 | FY2021 | FY2022\n"
        "Revenue | 150.2 | 158.9 | 165.0\n"
        "EBITDA | 24.1 | 26.0 | 27.4\n"
        "Revenue growth | 5.8 | 5.8 | 3.8"
    )
    read = _read(text)
    assert read[("revenue", "FY2021")] == 158.9
    assert read[("ebitda", "FY2022")] == 27.4
    assert len(read) == 6  # the growth row is not a KPI of the table


def test_whitespace_table_negative_numbers_and_header_scale() -> None:
    text = (
        "Cash flow statement (EUR thousand)\n"
        "                      FY2023     FY2024\n"
        "Operating cash flow   24,000     26,100\n"
        "Capital expenditures  (9,200)    (10,100)"
    )
    read = _read(text)
    assert read[("operating_cash_flow", "FY2024")] == pytest.approx(26.1)
    assert read[("capex", "FY2023")] == pytest.approx(-9.2)


def test_row_with_a_missing_cell_is_skipped_not_misaligned() -> None:
    text = "Line item | FY2022 | FY2023 | FY2024\nRevenue | 165.0 | 168.0"
    assert _read(text) == {}


def test_quotes_are_verbatim_slices_of_the_text() -> None:
    text = (
        "Intro line.\nLine item | FY2023 | FY2024\nRevenue | 168.0 | 182.4\n"
        "Net revenue for FY2024 reached EUR 182.4 million."
    )
    for candidate in parse_chunk(text, INDEX):
        assert isinstance(candidate, Candidate)
        quote = text[candidate.start : candidate.end]
        assert quote and quote == quote.strip()
        assert value_in_quote(candidate.value, quote)


@pytest.mark.parametrize(
    ("value", "quote", "found"),
    [
        (182.4, "Net revenue for FY2024 reached EUR 182.4 million", True),
        (182.4, "revenue of EUR 182,4 m", True),
        (182.4, "Revenue | 150.2 | 182.4", True),
        (182.4, "EUR 0.1824 billion", True),
        (38.5, "Gross margin was 38.5 percent", True),
        (182.4, "Net revenue for FY2024 reached EUR 179 million", False),
        (2024.0, "revenue in FY2024", False),
        (18.24, "revenue 182.4", False),
    ],
)
def test_value_in_quote(value: float, quote: str, found: bool) -> None:
    assert value_in_quote(value, quote) is found
