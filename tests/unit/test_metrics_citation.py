"""Citation metrics and verifier scores on hand computed examples."""

from __future__ import annotations

import pytest

from ainma.evaluation.metrics.citation import (
    CitedClaim,
    GoldFact,
    QuotedCitation,
    citation_counts,
    claim_is_unsupported,
    claim_matches_fact,
)
from ainma.evaluation.metrics.numbers import extract_numbers, numbers_covered, value_in_text
from ainma.evaluation.metrics.verifier import recall_by_group, verifier_scores

REVENUE = GoldFact("f1", 182.4, ("revenue", "FY2024"), frozenset({"c1", "c1b"}))
MARGIN = GoldFact("f2", 38.5, ("gross margin", "FY2024"), frozenset({"c2"}))


def test_extract_numbers_ignores_period_labels_and_normalises_separators() -> None:
    assert extract_numbers("Revenue FY2024 was EUR 1,234.5 million, up 8.6%.") == [1234.5, 8.6]
    assert extract_numbers("Umsatz 182,4 Mio") == [182.4]
    assert extract_numbers("in 2024 the largest customer had 17 percent.") == [2024.0, 17.0]
    assert value_in_text(182.4, "EUR 182.4m of revenue")
    assert not value_in_text(182.4, "EUR 1182.4m")


def test_numbers_covered_uses_the_union_of_quotes() -> None:
    claim = "Revenue grew from 168.0 to 182.4"
    assert numbers_covered(claim, ["EUR 168.0 million", "EUR 182.4 million"])
    assert not numbers_covered(claim, ["EUR 168.0 million"])


def test_claim_matches_fact_needs_value_and_all_keywords() -> None:
    assert claim_matches_fact("Net revenue for FY2024 reached EUR 182.4 million.", REVENUE)
    assert not claim_matches_fact("Net revenue for FY2023 reached EUR 182.4 million.", REVENUE)
    assert not claim_matches_fact("Net revenue for FY2024 reached EUR 179 million.", REVENUE)


def test_citation_precision_and_recall_by_hand() -> None:
    # Claim A matches f1 and cites c1 (in its support set): correct.
    # Claim B has the margin value but the wrong period, so it matches no fact: incorrect.
    # Claim C matches f2 but cites c9 outside its support set: incorrect.
    # Precision = 1/3. Covered facts = {f1}, so recall = 1/2.
    claims = [
        CitedClaim("Net revenue for FY2024 reached EUR 182.4 million.", ("c1",)),
        CitedClaim("Gross margin was 38.5 percent in FY2023.", ("c2",)),
        CitedClaim("Gross margin was 38.5 percent in FY2024.", ("c9",)),
    ]
    counts = citation_counts(claims, [REVENUE, MARGIN])
    assert (counts.n_claims, counts.n_correct, counts.n_facts, counts.n_covered) == (3, 1, 2, 1)
    assert counts.precision == pytest.approx(1 / 3)
    assert counts.recall == pytest.approx(1 / 2)


def test_citation_counts_without_claims_have_no_precision() -> None:
    counts = citation_counts([], [REVENUE])
    assert counts.precision is None
    assert counts.recall == 0.0


def test_unsupported_claim_detection() -> None:
    chunk = "Net revenue for FY2024 reached EUR 182.4 million (FY2023: EUR 168.0 million)."
    good = QuotedCitation("EUR 182.4 million", chunk)
    not_verbatim = QuotedCitation("EUR 182.5 million", chunk)
    no_number = QuotedCitation("Net revenue for FY2024", chunk)
    claim = "Revenue was EUR 182.4 million."
    assert not claim_is_unsupported(claim, [good])
    assert claim_is_unsupported(claim, [not_verbatim])  # quote is not a substring of the chunk
    assert claim_is_unsupported(claim, [no_number])  # 182.4 is not in the quote


def test_verifier_scores_by_hand() -> None:
    # truth:   S  S  P  P  U  U
    # flagged: F  T  T  F  T  T
    # Not fully supported = P, P, U, U (4). Flagged among them: P 1/2, U 2/2, together 3/4.
    # Flagged total = 4 (positions 2, 3, 5, 6), of which 3 are truly not supported: precision 3/4.
    # Supported claims flagged: 1 of 2.
    truth = ["supported", "supported", "partial", "partial", "unsupported", "unsupported"]
    flagged = [False, True, True, False, True, True]
    scores = verifier_scores(truth, flagged)
    assert scores.recall_unsupported == pytest.approx(1.0)
    assert scores.recall_partial == pytest.approx(0.5)
    assert scores.recall_not_supported == pytest.approx(0.75)
    assert scores.precision == pytest.approx(0.75)
    assert scores.false_flag_rate == pytest.approx(0.5)


def test_verifier_recall_by_group() -> None:
    groups = ["altered_number", "altered_number", "half_true", "none"]
    truth = ["unsupported", "unsupported", "partial", "supported"]
    flagged = [True, False, True, False]
    assert recall_by_group(groups, truth, flagged) == {
        "altered_number": 0.5,
        "half_true": 1.0,
        "none": None,
    }


def test_verifier_scores_reject_length_mismatch() -> None:
    with pytest.raises(ValueError, match="same length"):
        verifier_scores(["supported"], [True, False])
