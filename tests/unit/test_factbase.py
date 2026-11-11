"""Structured fact base: provenance, access inside every tool, typed requests only (D91)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainma.contracts import AccessContext
from ainma.factbase import (
    BuyerFilterRequest,
    ComparablesRequest,
    FactBase,
    LookupRequest,
)

SEED_DIR = Path("data/synthetic/1234")
pytestmark = pytest.mark.skipif(
    not (SEED_DIR / "structured" / "factbase.json").exists(), reason="run `make data` first"
)

ANALYST = AccessContext(user_id="u_analyst", allowed_deal_ids=frozenset({"deal_aurora"}))
OUTSIDER = AccessContext(user_id="u_outsider", allowed_deal_ids=frozenset())


@pytest.fixture(scope="module")
def base() -> FactBase:
    loaded = FactBase.load(SEED_DIR)
    assert loaded is not None
    return loaded


def test_deal_lookup_defaults_to_the_target_and_cites_the_document_of_record(
    base: FactBase,
) -> None:
    (fact,) = base.lookup(
        LookupRequest(metric="revenue", period="FY2024"), access=ANALYST, deal_id="deal_aurora"
    )
    assert fact.entity == "Aurora Components" and fact.value == pytest.approx(182.4)
    assert int(fact.provenance.tier) == 2  # a deal document, not the trade press
    citation = fact.provenance.citation()
    assert "182.4" in citation.quote
    # the trade press figure (179) is kept as a disagreeing source, not dropped
    assert any(abs(o.value - 179.0) < 1e-9 for o in fact.disagreements)


def test_access_is_applied_inside_the_tool(base: FactBase) -> None:
    request = LookupRequest(metric="revenue", entity="Aurora Components", period="FY2024")
    assert base.lookup(request, access=OUTSIDER, deal_id="deal_aurora") == []
    assert base.lookup(request, access=OUTSIDER, deal_id=None) == []
    assert base.comparables(ComparablesRequest(metric="revenue"), access=OUTSIDER) == []


def test_the_similarly_named_company_is_not_the_target(base: FactBase) -> None:
    facts = base.lookup(LookupRequest(metric="revenue"), access=ANALYST, deal_id="deal_aurora")
    assert facts and {f.entity for f in facts} == {"Aurora Components"}


def test_question_metric_aliases_and_buyer_filter(base: FactBase) -> None:
    lead = AccessContext(user_id="u_lead", allowed_deal_ids=frozenset())
    rows = base.buyer_facts(BuyerFilterRequest(metric="fund_size", min_value=1000.0), access=lead)
    assert rows and all(r.metric == "aum" and r.value >= 1000.0 for r in rows)
    assert all(r.entity_id and r.entity_id.startswith("buyer_") for r in rows)


def test_comparables_cover_the_visible_deal_targets_only(base: FactBase) -> None:
    lead = AccessContext(
        user_id="u_lead", allowed_deal_ids=frozenset({"deal_aurora", "deal_borealis"})
    )
    rows = base.comparables(ComparablesRequest(metric="revenue", period="FY2024"), access=lead)
    assert {r.deal_id for r in rows} == {"deal_aurora", "deal_borealis"}


def test_requests_are_strict_models() -> None:
    with pytest.raises(ValueError):
        LookupRequest.model_validate({"metric": "revenue", "sql": "DROP TABLE facts"})
