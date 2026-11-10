"""Regression tests for the offline writer and judge rules, on tiny hand written passages."""

from __future__ import annotations

from datetime import date

import pytest

from ainma.llm.providers.mock_tasks import judge_support
from ainma.pipeline.rules import claim_text, evidence_facts, select_facts, subject_of
from ainma.pipeline.schemas import NumberedPassage
from ainma.pipeline.understand import topic_of, understand_rules
from ainma.retrieval.entities import entity_tokens
from ainma.retrieval.lexicon import detect_metrics, target_metrics
from ainma.retrieval.quantities import STATIC_PERIOD, extract_facts_rules

TABLE = (
    "10. Income statement\n\n"
    "EUR m | FY2020 | FY2021 | FY2022 | FY2023 | FY2024\n"
    "Revenue | 140.1 | 152.6 | 163.4 | 168.0 | 182.4\n"
    "Capital expenditure | 5.6 | 6.0 | 6.2 | 6.9 | 7.9"
)


def passage(n: int, text: str, title: str = "Project Aurora, CIM") -> NumberedPassage:
    return NumberedPassage(n=n, chunk_id=f"ch{n}", text=text, doc_title=title, tier=2)


# ---- the metric lexicon covers the paraphrase families of the sources ----------------------------


@pytest.mark.parametrize(
    ("sentence", "metric", "period", "value"),
    [
        ("Turnover climbed to EUR 1,053.5m over fiscal 2024.", "revenue", "FY2024", 1053.5),
        (
            "Sales totalled EUR 90.0 million for the year ended 31 December 2022.",
            "revenue",
            "FY2022",
            90.0,
        ),
        (
            "Earnings before interest, tax, depreciation and amortisation stood at "
            "EUR 31.8 million for fiscal 2024.",
            "ebitda",
            "FY2024",
            31.8,
        ),
        (
            "Operating earnings before depreciation represented 17.4 percent of sales "
            "in fiscal 2024.",
            "ebitda_margin",
            "FY2024",
            17.4,
        ),
        (
            "After direct production costs, 38.5 percent of sales remained as profit "
            "in fiscal 2024.",
            "gross_margin",
            "FY2024",
            38.5,
        ),
        (
            "Borrowings less cash stood at EUR 66.0m at the close of FY2024.",
            "net_debt",
            "FY2024",
            66.0,
        ),
        ("Aurora is believed to employ around 1,000 people.", "headcount", None, 1000.0),
        (
            "Manufacturing is spread over 7 plants as of fiscal 2024.",
            "production_sites",
            "FY2024",
            7.0,
        ),
        (
            "On a cash-free and debt-free basis the business is priced at EUR 478.8m.",
            "enterprise_value",
            None,
            478.8,
        ),
        (
            "The vehicle began its life as an investor pool in 2019.",
            "fund_vintage_year",
            STATIC_PERIOD,
            2019.0,
        ),
        (
            "Standard sell-side process foresees 2 bidding rounds.",
            "bidder_rounds",
            STATIC_PERIOD,
            2.0,
        ),
    ],
)
def test_paraphrase_families_are_mapped_to_one_metric(
    sentence: str, metric: str, period: str | None, value: float
) -> None:
    facts = extract_facts_rules(sentence)
    assert [(f.metric, f.period, f.value) for f in facts] == [(metric, period, value)]


def test_a_percent_of_sales_is_not_revenue() -> None:
    facts = extract_facts_rules("A single client contributed 17.0 percent of sales in fiscal 2024.")
    assert [f.metric for f in facts] == ["top_customer_share"]


def test_a_range_phrase_gives_a_minimum_and_a_maximum() -> None:
    facts = extract_facts_rules(
        "The fund targets equity tickets of EUR 40.0 million to EUR 150.0 million per transaction."
    )
    assert [(f.metric, f.value) for f in facts] == [("ticket_min", 40.0), ("ticket_max", 150.0)]


def test_table_cells_become_facts_with_the_period_of_their_column() -> None:
    facts = extract_facts_rules(TABLE)
    revenue = {f.period: f.value for f in facts if f.metric == "revenue"}
    assert revenue["FY2024"] == 182.4 and revenue["FY2020"] == 140.1
    assert all(f.from_table and f.unit == "EUR m" for f in facts)
    capex = next(f for f in facts if f.metric == "capex" and f.period == "FY2022")
    assert TABLE[capex.start : capex.end] == "6.2"


def test_question_targets_exclude_the_base_of_a_ratio_and_conditions() -> None:
    assert target_metrics("What share of FY2024 revenue came from the largest customer?") == [
        "top_customer_share"
    ]
    assert target_metrics("How much would shareholders receive after net debt is settled?") == [
        "equity_value"
    ]
    assert detect_metrics(
        "What were the earnings before interest, tax, depreciation and amortisation?"
    ) == ["ebitda"]


# ---- understand ---------------------------------------------------------------------------------


def test_topic_keeps_the_first_letter_of_the_entity() -> None:
    assert (
        topic_of("What was Aurora Components's gross margin?") == "Aurora Components's gross margin"
    )
    assert topic_of("How many people does Estell employ?") == "people does Estell employ"


def test_decomposition_keeps_metric_names_whole_and_carries_the_entity() -> None:
    long_name = (
        "What were Merium's earnings before interest, tax, depreciation and amortisation in FY2022?"
    )
    assert understand_rules(long_name).sub_questions == [long_name]
    compound = understand_rules(
        "What was Aurora Components's gross margin in FY2024, and what share of FY2024 "
        "revenue came from its largest customer?"
    )
    assert compound.sub_questions[1].endswith("Aurora Components")
    assert compound.metrics == ["gross_margin", "top_customer_share"]
    comparison = understand_rules("How did Aurora's revenue change between FY2023 and FY2024?")
    assert len(comparison.sub_questions) == 1 and comparison.periods == ["FY2023", "FY2024"]


# ---- writer -------------------------------------------------------------------------------------


def test_claims_are_canonical_and_the_quote_is_verbatim() -> None:
    passages = [passage(1, "Turnover climbed to EUR 182.4 million over fiscal 2024. Other text.")]
    question = "How large was Aurora Components's turnover in the year ended 31 December 2024?"
    selected = select_facts(question, passages, limit=4, entity=entity_tokens(question))
    assert selected is not None and len(selected) == 1
    chosen = selected[0]
    text = claim_text(subject_of(question), chosen.fact, chosen.period)
    assert text == "Aurora Components revenue for FY2024 was EUR 182.4 million."
    assert chosen.fact.sentence in passages[0].text


def test_a_table_cell_is_quoted_as_its_row() -> None:
    question = "What was Aurora Components's capital expenditure in FY2022?"
    selected = select_facts(question, [passage(1, TABLE)], limit=4, entity=entity_tokens(question))
    assert selected is not None and len(selected) == 1
    assert selected[0].fact.sentence == "Capital expenditure | 5.6 | 6.0 | 6.2 | 6.9 | 7.9"
    assert selected[0].fact.value == 6.2


def test_a_sentence_about_another_company_is_never_a_claim() -> None:
    question = "What was Aurora Components's revenue in FY2024?"
    entity = entity_tokens(question)
    others = [
        passage(1, "Tarnar Industries generated revenue of EUR 193.4m in FY2024."),
        passage(2, "Aurore Components generated revenue of EUR 173.6 million in FY2024."),
        passage(3, "Aurora booked roughly EUR 179 million of revenue in 2024."),
    ]
    selected = select_facts(question, others, limit=4, entity=entity)
    assert selected is not None
    assert [s.fact.value for s in selected] == [179.0]


# ---- judge --------------------------------------------------------------------------------------

CIM = "Net revenue for FY2024 reached EUR 182.4 million (FY2023: EUR 168.0 million)."


@pytest.mark.parametrize(
    ("claim", "label"),
    [
        ("Aurora Components revenue for FY2024 was EUR 182.4 million.", "supported"),
        ("Aurora Components revenue for FY2023 was EUR 168.0 million.", "supported"),
        ("Aurora Components revenue for FY2024 was EUR 150.2 million.", "unsupported"),
        ("Aurora Components revenue for FY2023 was EUR 182.4 million.", "unsupported"),
        # the quote names nobody, so another name cannot be contradicted (see the next test)
        ("Carix Systems revenue for FY2024 was EUR 182.4 million.", "supported"),
        (
            "Aurora Components revenue for FY2024 was EUR 182.4 million and Aurora Components "
            "headcount at the end of FY2024 was 3,288.",
            "partial",
        ),
    ],
)
def test_judge_binds_value_period_and_entity(claim: str, label: str) -> None:
    context = f"Project Aurora, Confidential Information Memorandum\n{CIM}"
    assert judge_support(claim, [CIM], context).label == label


def test_judge_reads_the_period_of_a_table_row_from_the_header_in_the_context() -> None:
    row = "Capital expenditure | 5.6 | 6.0 | 6.2 | 6.9 | 7.9"
    context = f"Project Aurora, financial model\n{TABLE}"
    good = "Aurora Components capital expenditure for FY2022 was EUR 6.2 million."
    wrong_period = "Aurora Components capital expenditure for FY2023 was EUR 6.2 million."
    assert judge_support(good, [row], context).label == "supported"
    assert judge_support(wrong_period, [row], context).label == "unsupported"
    assert [f.period for f in evidence_facts(row, context) if f.value == 6.2] == ["FY2022"]


def test_judge_flags_a_claim_about_a_company_the_source_does_not_name() -> None:
    named = "Aurora Components reported net revenue of EUR 182.4 million for FY2024."
    other = "Carix Systems revenue for FY2024 was EUR 182.4 million."
    near = "Aurore Components revenue for FY2024 was EUR 182.4 million."
    same = "Aurora revenue for FY2024 was EUR 182.4 million."
    assert judge_support(other, [named], named).label == "unsupported"
    assert judge_support(
        near, ["Aurora Components reported EUR 182.4 million in FY2024 revenue."], named
    ).label
    assert judge_support(same, [named], named).label == "supported"


def test_a_sentence_about_a_sibling_entity_is_skipped_by_the_writer() -> None:
    question = "What EV to EBITDA multiple was paid in Precedent transaction Ravell?"
    sentences = [
        passage(1, "The EV to EBITDA multiple paid in Precedent transaction Senix was 11.7x."),
        passage(2, "The EV to EBITDA multiple paid in Precedent transaction Ravell was 12.9x."),
    ]
    selected = select_facts(question, sentences, limit=4, entity=entity_tokens(question))
    assert selected is not None and [s.fact.value for s in selected] == [12.9]


# ---- periods of undated figures --------------------------------------------------------------


def dated(n: int, text: str, published: date) -> NumberedPassage:
    return NumberedPassage(
        n=n, chunk_id=f"ch{n}", text=text, doc_title="Trade press", tier=4, published_on=published
    )


def test_an_undated_press_figure_speaks_about_the_year_before_its_publication() -> None:
    press = dated(1, "Aurora is believed to employ around 1,000 people.", date(2025, 2, 2))
    entity = entity_tokens("How many people does Aurora employ?")
    in_2024 = select_facts(
        "How many people did Aurora employ at the end of FY2024?", [press], limit=4, entity=entity
    )
    in_2022 = select_facts(
        "How many people did Aurora employ at the end of FY2022?", [press], limit=4, entity=entity
    )
    assert in_2024 is not None and [s.fact.value for s in in_2024] == [1000.0]
    assert in_2024[0].period == "FY2024"
    assert in_2022 == []  # an article of 2025 is not evidence about FY2022


def test_without_a_period_the_latest_stated_period_is_answered() -> None:
    entity = entity_tokens("How many production sites does Aurora operate?")
    current = dated(1, "Aurora runs 6 production sites as of FY2024.", date(2025, 3, 14))
    old = dated(2, "Aurora runs 2 production sites as of FY2022.", date(2023, 3, 1))
    selected = select_facts(
        "How many production sites does Aurora operate?", [current, old], limit=4, entity=entity
    )
    assert selected is not None and [s.fact.value for s in selected] == [6.0]
    only_old = select_facts(
        "How many production sites does Aurora operate?", [old], limit=4, entity=entity
    )
    assert only_old is not None and [s.period for s in only_old] == ["FY2022"]
