"""Named entities of a question, and the entity aware parts of the retrieval."""

from __future__ import annotations

import pytest

from ainma.retrieval.config import RankerConfig
from ainma.retrieval.entities import entity_overlap, entity_phrases, entity_tokens
from ainma.retrieval.ranker import final_score
from ainma.retrieval.rerank import FeatureReranker


@pytest.mark.parametrize(
    ("question", "phrases"),
    [
        ("What was Aurora's FY2024 revenue?", ["Aurora"]),
        ("What was Aurora Components's EBITDA in FY2020?", ["Aurora Components"]),
        ("How much revenue did Carane Foods report for FY2024 in EUR?", ["Carane Foods"]),
        (
            "How much did Ostis Industries control in the year ended 31 December 2024?",
            ["Ostis Industries"],
        ),
        (
            "What is the revenue of Aurora Components and Aurore Components?",
            ["Aurora Components", "Aurore Components"],
        ),
        ("what is the gross margin?", []),
    ],
)
def test_entity_phrases(question: str, phrases: list[str]) -> None:
    assert entity_phrases(question) == phrases


def test_entity_tokens_are_stemmed_and_distinct() -> None:
    # the brand only: `Water Systems` is a descriptor, like `Components` or `Capital Partners`
    assert entity_tokens("What did Merium Water Systems report? Merium also grew.") == ["merium"]
    assert entity_tokens("How did Aurora Components's revenue change?") == ["aurora"]


def test_entity_overlap_weighs_rare_tokens_more() -> None:
    idf = {"aurora": 5.0, "component": 0.5}.get
    wanted = ["aurora", "component"]
    named = entity_overlap(wanted, {"aurora"}, lambda t: idf(t, 1.0))
    generic = entity_overlap(wanted, {"component"}, lambda t: idf(t, 1.0))
    assert named is not None and generic is not None
    assert named == pytest.approx(5.0 / 5.5)
    assert generic == pytest.approx(0.5 / 5.5)
    assert entity_overlap([], {"aurora"}, None) is None


def test_reranker_prefers_the_passage_of_the_named_company() -> None:
    reranker = FeatureReranker()
    query = "What was Aurora's FY2024 revenue?"
    about = "Net revenue for FY2024 reached EUR 182.4 million."
    other = "Tarnar Industries generated revenue of EUR 193.4m in FY2024."
    terms_about = {"aurora", "net", "revenue"}
    terms_other = {"tarnar", "industry", "revenue"}
    scores = reranker.score(query, [about, other], document_terms=[terms_about, terms_other])
    assert scores[0] > scores[1]
    # without the document terms the passage text decides (neither names the company)
    assert reranker.features(query, other)["entity"] == 0.0


def test_trust_exponent_tempers_the_source_ranker() -> None:
    plain = final_score(relevance=0.9, tier_weight=0.45, recency=0.5, status=1.0, bonus=0.0)
    soft = final_score(
        relevance=0.9, tier_weight=0.45, recency=0.5, status=1.0, bonus=0.0, exponent=0.5
    )
    assert plain == pytest.approx(0.9 * 0.45 * 0.5)
    assert soft == pytest.approx(0.9 * (0.45 * 0.5) ** 0.5)
    scoped = final_score(
        relevance=0.9, tier_weight=1.0, recency=1.0, status=1.0, bonus=0.0, scope=0.7
    )
    assert scoped == pytest.approx(0.63)
    assert RankerConfig().out_of_scope_weight < 1.0


@pytest.mark.parametrize(
    "name",
    [
        "Kesent Analytics",
        "Zanon Containers",
        "Vexeth Logistics",
        "Merium Water Systems",
        "Yorium Foods",
    ],
)
def test_the_descriptor_is_dropped_whatever_the_stemmer_does_to_it(name: str) -> None:
    """`Analytics` is stemmed to `analytic` and `Containers` to `container`: a descriptor list
    written in the plural must still drop them, or a document that says only `Kesent` is gated
    out of the answer about `Kesent Analytics`."""
    brand = name.split()[0].lower()
    assert entity_tokens(f"What did {name} report?") == [brand]
