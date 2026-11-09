from __future__ import annotations

import pytest
from pydantic import ValidationError

from ainma.contracts import (
    VALUE_CONTRACT,
    Answer,
    BuyerCard,
    Chunk,
    Claim,
    ClaimStatus,
    DocType,
    DocumentMeta,
    KpiValue,
    SourceTier,
)
from tests.conftest import load_payload


def test_answer_payloads_validate() -> None:
    contradiction = Answer.model_validate(load_payload("answer_contradiction.json"))
    abstention = Answer.model_validate(load_payload("answer_abstention.json"))
    assert contradiction.contradictions[0].sides[0].claim_id == "c1"
    assert abstention.abstained and abstention.claims[0].status is ClaimStatus.MISSING
    assert contradiction.value_contract == VALUE_CONTRACT == abstention.value_contract


def test_buyer_card_payload_validates() -> None:
    card = BuyerCard.model_validate(load_payload("buyer_card.json"))
    assert card.results[1].status.value == "unknown"


def test_sourced_claim_needs_a_citation() -> None:
    with pytest.raises(ValidationError):
        Claim(id="c", text="x", status=ClaimStatus.SOURCED)


def test_inferred_claim_needs_parents() -> None:
    with pytest.raises(ValidationError):
        Claim(id="c", text="x", status=ClaimStatus.INFERRED)


def test_missing_claim_cannot_carry_citations() -> None:
    payload = load_payload("answer_contradiction.json")["claims"][0]
    payload.update(status="missing", derived_from=[], verification=None, flags=[])
    with pytest.raises(ValidationError):
        Claim.model_validate(payload)


def test_abstained_answer_cannot_hold_sourced_claims() -> None:
    payload = load_payload("answer_contradiction.json")
    payload["abstained"] = True
    with pytest.raises(ValidationError):
        Answer.model_validate(payload)


def test_extra_fields_are_forbidden() -> None:
    payload = load_payload("answer_abstention.json")
    payload["surprise"] = 1
    with pytest.raises(ValidationError):
        Answer.model_validate(payload)


def test_chunk_span_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        Chunk(
            id="c",
            document_id="d",
            page=1,
            char_start=5,
            char_end=5,
            text="x",
            doc_type=DocType.WEB,
        )


def test_tier_is_derived_from_doc_type() -> None:
    meta = DocumentMeta(
        id="d", title="t", doc_type=DocType.PRESS_ARTICLE, n_pages=1, sha256="0" * 64
    )
    assert meta.tier is SourceTier.T4
    assert meta.model_dump()["tier"] == SourceTier.T4


def test_kpi_value_status_rules() -> None:
    with pytest.raises(ValidationError):
        KpiValue(kpi_id="k", period="FY2024", value=1.0, unit="EUR m", status="sourced")
    with pytest.raises(ValidationError):
        KpiValue(kpi_id="k", period="FY2024", value=1.0, unit="%", status="computed")
    with pytest.raises(ValidationError):
        KpiValue(kpi_id="k", period="FY2024", value=1.0, unit="%", status="missing")
    assert KpiValue(kpi_id="k", period="FY2024", value=None, unit="%", status="missing")
