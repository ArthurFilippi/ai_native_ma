"""Event scoring on a hand built example."""

from __future__ import annotations

from datetime import date

from ainma.contracts import Citation, DocType, MarketEvent, SourceTier
from ainma.evaluation.metrics.news import event_counts
from ainma.truth import NewsEventTruth

CITE = Citation(
    chunk_id="c", document_id="d", doc_title="t", doc_type=DocType.PRESS_ARTICLE,
    tier=SourceTier.T4, page=1, char_start=0, char_end=1, quote="q",
)  # fmt: skip


def _truth(
    kind: str, cp: str, status: str, titles: int = 1, value: float | None = None
) -> NewsEventTruth:
    return NewsEventTruth(
        id=f"t_{kind}_{cp}", kind=kind, entity="b1", counterparty=cp, event_date=date(2025, 1, 1),  # type: ignore[arg-type]
        status=status, value=value, item_titles=[f"x{i}" for i in range(titles)],  # type: ignore[arg-type]
    )  # fmt: skip


def _event(kind: str, cp: str, status: str, n: int = 1, value: float | None = None) -> MarketEvent:
    return MarketEvent(
        id=f"e_{kind}_{cp}", kind=kind, actor="B", buyer_id="b1", counterparty=cp,  # type: ignore[arg-type]
        status=status, value_eur_m=value, citations=[CITE], n_reports=n,  # type: ignore[arg-type]
    )  # fmt: skip


def test_event_counts_hand_example() -> None:
    truth = [
        _truth("acquisition", "T", "confirmed", titles=2),
        _truth("rumour", "R", "denied", titles=2),
        _truth("price", "T", "corrected", titles=2, value=102.0),
        _truth("leadership_change", "P", "confirmed"),
    ]
    extracted = [
        _event("acquisition", "t", "confirmed", n=2),
        _event("rumour", "R", "unconfirmed", n=1),  # the denial was missed: unsafe
        _event("price", "T", "corrected", n=2, value=102.0),
        _event("acquisition", "Z", "confirmed"),  # not in the truth
    ]
    c = event_counts(extracted, truth)
    assert (c.n_truth, c.n_extracted, c.n_matched) == (4, 4, 3)
    assert c.n_status_correct == 2
    assert (c.n_price, c.n_price_value_correct) == (1, 1)
    assert (c.n_denied, c.n_denied_as_fact) == (1, 1)
    assert (c.n_duplicated, c.n_duplicates_merged) == (1, 1)
