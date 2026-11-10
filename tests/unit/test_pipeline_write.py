from __future__ import annotations

from ainma.contracts import ClaimStatus
from ainma.pipeline.schemas import DraftClaim, DraftEvidence, WriteResult
from ainma.pipeline.write import build_citation, build_claims, locate_quote
from ainma.retrieval import RetrievalConfig, search
from ainma.store import SqliteStore
from tests.fixtures.tiny import chunk_document, tiny_documents

CIM = next(d for d in tiny_documents() if d.meta.id == "doc_cim")
CIM_CHUNKS = {c.id: c for c in chunk_document(CIM)}
REVENUE_CHUNK = CIM_CHUNKS["doc_cim_p2_00"]
MARGIN_CHUNK = CIM_CHUNKS["doc_cim_p2_01"]
QUOTE = "EUR 182.4 million"


async def _hits(store: SqliteStore):  # type: ignore[no-untyped-def]
    access = await store.access_for("u_analyst")
    config = RetrievalConfig(system="A5", top_k=20)
    return await search(
        "net revenue gross margin", store=store, access=access, deal_id="deal_aurora", config=config
    )


def test_locate_quote_exact_and_whitespace_tolerant() -> None:
    text = "alpha  beta\ngamma delta"
    assert locate_quote("beta", text) == (7, "beta")
    index, exact = locate_quote("alpha beta gamma", text) or (-1, "")
    assert (index, exact) == (0, "alpha  beta\ngamma")
    assert text[index : index + len(exact)] == exact
    assert locate_quote("epsilon", text) is None
    assert locate_quote("   ", text) is None


def test_citation_offsets_are_exact_page_offsets() -> None:
    citation = build_citation(REVENUE_CHUNK, CIM.meta, QUOTE)
    assert citation is not None
    page = CIM.pages[citation.page - 1]
    assert page[citation.char_start : citation.char_end] == QUOTE
    assert citation.page == 2 and citation.tier == 2 and citation.doc_title == CIM.meta.title
    # a chunk that does not start at offset 0 of its page keeps page based offsets
    second = build_citation(MARGIN_CHUNK, CIM.meta, "38.5 percent")
    assert second is not None
    assert CIM.pages[1][second.char_start : second.char_end] == "38.5 percent"
    assert second.char_start == MARGIN_CHUNK.char_start + MARGIN_CHUNK.text.index("38.5 percent")


def test_non_verbatim_quote_builds_no_citation() -> None:
    assert build_citation(REVENUE_CHUNK, CIM.meta, "EUR 190.0 million") is None
    assert build_citation(REVENUE_CHUNK, CIM.meta, "net revenue for fy2024") is None  # case


async def test_writer_claims_with_bad_evidence_are_rejected(tiny_store: SqliteStore) -> None:
    hits = await _hits(tiny_store)
    numbers = {h.chunk.id: i for i, h in enumerate(hits, start=1)}
    revenue_no = numbers["doc_cim_p2_00"]
    result = WriteResult(
        claims=[
            DraftClaim(
                id="d1",
                text="Revenue was EUR 182.4 million.",
                status="sourced",
                evidence=[DraftEvidence(passage=revenue_no, quote=QUOTE + " in FY2024")],
            ),
            DraftClaim(
                id="d2",
                text="Revenue was EUR 190.0 million.",
                status="sourced",
                evidence=[DraftEvidence(passage=revenue_no, quote="EUR 190.0 million")],
            ),
            DraftClaim(
                id="d3",
                text="Revenue was EUR 182.4 million.",
                status="sourced",
                evidence=[DraftEvidence(passage=99, quote=QUOTE)],
            ),
            DraftClaim(
                id="d4",
                text="Short quote.",
                status="sourced",
                evidence=[DraftEvidence(passage=revenue_no, quote="EUR")],
            ),
            DraftClaim(id="d5", text="No evidence.", status="sourced"),
            DraftClaim(
                id="d6",
                text="Revenue was EUR 182.4 million.",
                status="sourced",
                evidence=[DraftEvidence(passage=revenue_no, quote=QUOTE)],
            ),
            DraftClaim(id="d7", text="Growth from d2.", status="inferred", derived_from=["d2"]),
            DraftClaim(id="d8", text="Growth from d6.", status="inferred", derived_from=["d6"]),
            DraftClaim(id="d9", text="Growth from nothing.", status="inferred"),
        ],
        missing=["guidance"],
    )
    outcome = build_claims(result, hits, min_quote_chars=10)
    assert [c.id for c in outcome.claims] == ["c1", "c2"]
    assert outcome.claims[0].status is ClaimStatus.SOURCED
    assert outcome.claims[1].status is ClaimStatus.INFERRED
    assert outcome.claims[1].derived_from == ["c1"]
    reasons = {d.text: d.reason for d in outcome.rejected}
    assert (
        reasons["Revenue was EUR 190.0 million."] == "quote is not a verbatim span of the passage"
    )
    assert reasons["Short quote."] == "quote too short"
    assert reasons["No evidence."] == "no evidence given"
    assert reasons["Growth from d2."].startswith("derived from a claim")
    assert outcome.missing == ["guidance"]
    citation = outcome.claims[0].citations[0]
    assert tiny_store is not None and citation.quote == QUOTE
