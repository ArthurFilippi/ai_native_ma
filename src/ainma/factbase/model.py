"""Records of the structured fact base. Every value carries the passage it comes from."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from ainma.contracts import Citation, DocStatus, DocType, SourceTier, Strict


class Provenance(Strict):
    """Where a structured value is stated: one verbatim passage of one stored document."""

    document_id: str
    doc_title: str
    doc_type: DocType
    tier: SourceTier
    published_on: date | None = None
    status: DocStatus = DocStatus.CURRENT
    chunk_id: str
    page: int = Field(ge=1)
    char_start: int = Field(ge=0)  # offsets inside the page text, as `Citation`
    char_end: int
    quote: str = Field(min_length=1)

    def citation(self) -> Citation:
        """The citation of this provenance, the same object a text claim carries."""
        return Citation(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            doc_title=self.doc_title,
            doc_type=self.doc_type,
            tier=self.tier,
            published_on=self.published_on,
            page=self.page,
            char_start=self.char_start,
            char_end=self.char_end,
            quote=self.quote,
        )


class SourcedValue(Strict):
    value: float
    provenance: Provenance


class StructuredFact(Strict):
    """One keyed value (entity, metric, period) and its source of record.

    The source of record is the current document of the best tier, then the most recent, then
    the lowest document id. `others` lists every other current document that states the same key:
    agreeing ones corroborate, disagreeing ones (beyond 0.5 percent) become contradictions.
    """

    id: str
    deal_id: str | None  # None: general layer (buyers, precedents)
    entity: str
    entity_id: str | None = None  # buyer id when the fact is about a buyer
    metric: str
    period: str  # "FY2024" or "static"
    value: float
    unit: str
    provenance: Provenance
    others: list[SourcedValue] = Field(default_factory=list)
    # values stated by superseded documents (a draft replaced by the executed version): never a
    # source of record, shown flagged so the reader sees what changed
    superseded: list[SourcedValue] = Field(default_factory=list)

    @property
    def disagreements(self) -> list[SourcedValue]:
        return [o for o in self.others if not agrees(o.value, self.value)]


class Company(Strict):
    """A deal's target company: the entity a deal question is about by default."""

    deal_id: str
    name: str
    sector: str
    geographies: list[str] = Field(default_factory=list)


class FactBaseFile(Strict):
    """`structured/factbase.json` of a seed."""

    synthetic: bool = True
    note: str = (
        "Synthetic structured fact base, built by the generator from the planted facts. Every "
        "value cites the passage of the document of record."
    )
    companies: list[Company]
    facts: list[StructuredFact]


TOLERANCE = 0.005


def agrees(a: float, b: float, tolerance: float = TOLERANCE) -> bool:
    scale = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / scale <= tolerance
