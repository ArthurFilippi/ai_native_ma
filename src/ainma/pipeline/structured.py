"""Route a sub-question to the structured fact base when it asks for one keyed value (D92).

A sub-question is routed when it names exactly one metric and at most one period, asks for no
change over time, and the typed `lookup` returns exactly one record in the user's scope. The
record becomes a SOURCED claim whose citation is its provenance (a verbatim span of the document
of record), and every disagreeing current document becomes a second claim, so the usual
verifier and contradiction stages treat both like text claims. Anything else goes to text search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ainma.contracts import AccessContext, Chunk, Claim, ClaimStatus, DocumentMeta
from ainma.factbase import FactBase, LookupRequest, StructuredFact, canonical_metric
from ainma.factbase.model import Provenance
from ainma.retrieval.entities import entity_phrases
from ainma.retrieval.lexicon import METRIC_BY_KEY, detect_periods, target_metrics
from ainma.store.base import Store

_GROWTH = re.compile(
    r"\b(grow|grew|growth|increase|decline|decrease|change|evolution|trend|compare|"
    r"comparison|versus|vs)\w*\b",
    re.IGNORECASE,
)


@dataclass
class Routed:
    record: StructuredFact
    claims: list[Claim]
    chunks: dict[str, Chunk] = field(default_factory=dict)
    documents: dict[str, DocumentMeta] = field(default_factory=dict)


def asks_for_change(question: str) -> bool:
    """A question about change over time is answered from text, where the writer derives the
    change from both periods; none of its sub-questions is routed."""
    return _GROWTH.search(question) is not None


def route_request(
    question: str, base: FactBase, *, access: AccessContext, deal_id: str | None
) -> StructuredFact | None:
    """The one record a sub-question asks for, or None (then text search answers it)."""
    if asks_for_change(question):
        return None
    metrics, periods = target_metrics(question), detect_periods(question)
    if len(metrics) != 1 or len(periods) > 1:
        return None
    period = periods[0] if periods else None
    candidates: list[str | None] = [*entity_phrases(question)]
    if deal_id is not None:
        candidates.append(None)  # the deal's target company
    for entity in candidates:
        found = base.lookup(
            LookupRequest(metric=metrics[0], entity=entity, period=period),
            access=access,
            deal_id=deal_id,
        )
        if len(found) == 1:
            return found[0]
        if found:
            return None  # several periods or entities: ambiguous, text search decides
    return None


def _value_text(record: StructuredFact, value: float) -> str:
    unit = record.unit
    if unit == "EUR m":
        return f"EUR {value:,.1f} million"
    if unit == "%":
        return f"{value:.1f} percent"
    if unit == "x":
        return f"{value:.1f}x"
    if record.metric.endswith("_year"):
        return str(int(value))
    number = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"
    return number if unit in ("count", "") else f"{number} {unit}"


def metric_label(metric: str) -> str:
    """The question vocabulary's label of a fact base metric (`aum` reads `assets under
    management`, `plants` reads `production sites`)."""
    known = METRIC_BY_KEY.get(metric)
    if known is None:
        key = next((k for k in METRIC_BY_KEY if canonical_metric(k) == metric), None)
        known = METRIC_BY_KEY.get(key) if key else None
    return known.label if known else metric.replace("_", " ")


def claim_text(record: StructuredFact, value: float) -> str:
    """The claim states the value only; its source is the citation (title, tier, date)."""
    label = metric_label(record.metric)
    period = "" if record.period == "static" else f" for {record.period}"
    return f"{record.entity} {label}{period} was {_value_text(record, value)}."


async def routed_claims(
    record: StructuredFact, *, store: Store, access: AccessContext, start: int
) -> Routed | None:
    """Claims of a record (source of record first, then each disagreeing document), with the
    chunks and documents the verifier and the flags need. None when a provenance is no longer
    visible (the store is the authority on access)."""
    out = Routed(record=record, claims=[])
    agreeing = [o.provenance for o in record.others if o not in record.disagreements]
    entries: list[tuple[float, list[Provenance]]] = [
        (record.value, [record.provenance, *agreeing]),  # the record, corroborated
        *((o.value, [o.provenance]) for o in record.disagreements),
        # a superseded draft is shown too; `apply_flags` marks it superseded
        *((o.value, [o.provenance]) for o in record.superseded),
    ]
    for offset, (value, provenances) in enumerate(entries):
        provenance = provenances[0]
        chunk = await store.get_chunk(provenance.chunk_id, access)
        document = await store.get_document(provenance.document_id, access)
        if chunk is None or document is None:
            if offset == 0:
                return None
            continue
        out.chunks[chunk.id] = chunk
        out.documents[document.id] = document
        citations = [provenance.citation()]
        for extra in provenances[1:]:
            more = await store.get_chunk(extra.chunk_id, access)
            more_doc = await store.get_document(extra.document_id, access)
            if more is None or more_doc is None or extra.citation() in citations:
                continue
            out.chunks[more.id] = more
            out.documents[more_doc.id] = more_doc
            citations.append(extra.citation())
        out.claims.append(
            Claim(
                id=f"s{start + offset}",
                text=claim_text(record, value),
                status=ClaimStatus.SOURCED,
                citations=citations,
                origin="structured",
            )
        )
    return out
