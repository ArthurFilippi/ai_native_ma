"""Market events read from the news against `truth/news_events.json` (D94)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ainma.contracts import MarketEvent
from ainma.truth import NewsEventTruth


@dataclass(frozen=True)
class EventCounts:
    n_truth: int
    n_extracted: int
    n_matched: int
    n_status_correct: int
    n_price: int  # matched price events
    n_price_value_correct: int  # within 0.5 percent of the (corrected) truth value
    n_denied: int  # denied rumours in the truth
    n_denied_as_fact: int  # ...that the system reported with another status: the unsafe error
    n_duplicated: int  # matched truth events reported by two items or more
    n_duplicates_merged: int  # ...that the system consolidated into one event with every report

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


def _key(kind: str, buyer: str | None, counterparty: str) -> tuple[str, str, str]:
    return (kind, buyer or "", " ".join(counterparty.lower().split()))


def event_counts(extracted: Sequence[MarketEvent], truth: Sequence[NewsEventTruth]) -> EventCounts:
    found = {_key(e.kind, e.buyer_id, e.counterparty): e for e in extracted}
    matched = status = n_price = price_ok = denied = denied_fact = dup = merged = 0
    for t in truth:
        e = found.get(_key(t.kind, t.entity, t.counterparty))
        if t.status == "denied":
            denied += 1
            if e is not None and e.status != "denied":
                denied_fact += 1
        if e is None:
            continue
        matched += 1
        status += int(e.status == t.status)
        if t.kind == "price" and t.value is not None:
            n_price += 1
            v = e.value_eur_m
            price_ok += int(v is not None and abs(v - t.value) <= 0.005 * abs(t.value))
        if len(t.item_titles) >= 2 and t.kind in ("acquisition", "leadership_change"):
            dup += 1
            merged += int(e.n_reports == len(t.item_titles))
    return EventCounts(
        n_truth=len(truth),
        n_extracted=len(extracted),
        n_matched=matched,
        n_status_correct=status,
        n_price=n_price,
        n_price_value_correct=price_ok,
        n_denied=denied,
        n_denied_as_fact=denied_fact,
        n_duplicated=dup,
        n_duplicates_merged=merged,
    )
