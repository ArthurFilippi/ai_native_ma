from __future__ import annotations

from ainma.contracts import Claim, ClaimStatus, Flag
from ainma.llm import build_mock_llm
from ainma.pipeline.verify import verify_claim, verify_claims
from ainma.pipeline.write import build_citation
from tests.fixtures.tiny import chunk_document, tiny_documents

CIM = next(d for d in tiny_documents() if d.meta.id == "doc_cim")
CHUNKS = {c.id: c for c in chunk_document(CIM)}
REVENUE = CHUNKS["doc_cim_p2_00"]
SENTENCE = REVENUE.text  # "Net revenue for FY2024 reached EUR 182.4 million (FY2023: ...)."


def _claim(claim_id: str, text: str, quote: str = SENTENCE) -> Claim:
    citation = build_citation(REVENUE, CIM.meta, quote)
    assert citation is not None
    return Claim(id=claim_id, text=text, status=ClaimStatus.SOURCED, citations=[citation])


async def test_honest_claim_passes_all_three_checks() -> None:
    verification, usage = await verify_claim(
        _claim("c1", "FY2024 revenue reached EUR 182.4 million."),
        chunks=CHUNKS,
        llm=build_mock_llm(),
    )
    assert verification.supported and verification.judge_label == "supported"
    assert [c.name for c in verification.checks] == ["verbatim_span", "numeric_match", "judge"]
    assert usage is not None


async def test_verifier_drops_doctored_claims_and_says_why() -> None:
    doctored_number = _claim("c1", "Net revenue for FY2024 reached EUR 190.0 million.")
    doctored_period = _claim("c2", "Net revenue for FY2023 reached EUR 182.4 million.")
    good = _claim("c4", "Net revenue for FY2024 reached EUR 182.4 million.")
    inferred = Claim(
        id="c5", text="Revenue grew.", status=ClaimStatus.INFERRED, derived_from=["c1"]
    )
    outcome = await verify_claims(
        [doctored_number, doctored_period, good, inferred],
        chunks=CHUNKS,
        llm=build_mock_llm(),
        drop_unverified=True,
    )
    assert [c.id for c in outcome.kept] == ["c4"]
    reasons = {d.text: d.reason for d in outcome.dropped}
    assert reasons[doctored_number.text].startswith("numeric_match")
    assert reasons[doctored_period.text].startswith("judge")
    assert reasons["Revenue grew."] == "a claim it derives from was dropped"
    assert outcome.kept[0].verification is not None and outcome.kept[0].verification.supported


async def test_doctored_quote_or_offsets_fail_the_verbatim_check() -> None:
    claim = _claim("c1", "Net revenue for FY2024 reached EUR 182.4 million.")
    forged_quote = claim.citations[0].model_copy(update={"quote": "EUR 999.9 million"})
    shifted = claim.citations[0].model_copy(update={"char_start": 5, "char_end": 5 + 77})
    for citation in (forged_quote, shifted):
        verification, _ = await verify_claim(
            claim.model_copy(update={"citations": [citation]}), chunks=CHUNKS, llm=build_mock_llm()
        )
        assert not verification.supported
        assert [c.name for c in verification.checks] == ["verbatim_span"]  # chain stops


async def test_keep_mode_flags_instead_of_dropping() -> None:
    bad = _claim("c1", "Net revenue for FY2024 reached EUR 190.0 million.")
    outcome = await verify_claims([bad], chunks=CHUNKS, llm=build_mock_llm(), drop_unverified=False)
    assert len(outcome.kept) == 1 and outcome.dropped == []
    assert Flag.UNVERIFIED in outcome.kept[0].flags
    assert outcome.kept[0].verification is not None and not outcome.kept[0].verification.supported
