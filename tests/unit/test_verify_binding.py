"""Binding of a number to its role, period and column (D89).

The two first cases are the errors observed on hand written documents and accepted by the old
verifier: a top five share read as the largest customer share, and an FY2022 table column read
as FY2024. They failed `binding_check` before it existed (it did not), and `numeric_match`
alone accepts both, which the first test pins.
"""

from __future__ import annotations

from ainma.pipeline.verify import binding_check, numeric_match

CUSTOMERS = (
    "Customer concentration remains moderate: the top five customers represented 41.0 percent "
    "of FY2024 revenue, and the largest single customer stayed below 14 percent."
)
TABLE = (
    "Adjusted EBITDA bridge (EUR m)\n"
    "Item | FY2022 | FY2023 | FY2024\n"
    "Reported EBITDA | 9.8 | 12.1 | 13.0\n"
    "Adjusted EBITDA | 11.2 | 13.4 | 14.6"
)
ROW = "Adjusted EBITDA | 11.2 | 13.4 | 14.6"


def test_numeric_match_alone_accepts_both_errors() -> None:
    assert numeric_match("Largest customer share for FY2024 was 41.0 percent.", CUSTOMERS)[0]
    assert numeric_match("Adjusted EBITDA for FY2024 was 11.2.", ROW, TABLE)[0]


def test_top_five_share_is_not_the_largest_customer() -> None:
    passed, detail = binding_check(
        "Largest customer share for FY2024 was 41.0 percent.", CUSTOMERS, CUSTOMERS
    )
    assert not passed and "top five" in detail


def test_fy2022_column_is_not_fy2024() -> None:
    passed, detail = binding_check("Adjusted EBITDA for FY2024 was 11.2.", ROW, TABLE)
    assert not passed and "FY2022" in detail


def test_the_right_column_and_role_pass() -> None:
    assert binding_check("Adjusted EBITDA for FY2024 was 14.6.", ROW, TABLE)[0]
    assert binding_check(
        "The top five customers represented 41.0 percent of FY2024 revenue.", CUSTOMERS, CUSTOMERS
    )[0]
    assert binding_check("The largest customer stayed below 14 percent.", CUSTOMERS, CUSTOMERS)[0]


def test_a_number_bound_to_another_year_in_a_sentence_fails() -> None:
    quote = "Revenue was EUR 140.1 million in FY2022 and EUR 182.4 million in FY2024."
    assert not binding_check("Revenue for FY2024 was EUR 140.1 million.", quote, quote)[0]
    assert binding_check("Revenue for FY2024 was EUR 182.4 million.", quote, quote)[0]


def test_claims_without_numbers_or_years_are_left_to_the_judge() -> None:
    assert binding_check("The company makes valves.", "It makes valves.", "")[0]
    assert binding_check("Revenue was EUR 182.4 million.", "EUR 182.4 million", "")[0]
