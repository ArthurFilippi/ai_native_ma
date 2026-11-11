"""Route a market question to the consolidated news events (D102).

A question with a market intent ("What has Orvane Capital acquired recently?", "Is X reported to
bid for Y?") asks for an event, not a passage. When the deal's events (D94) are passed to `ask`,
the events whose actor or counterparty the question names, and whose kind the question asks for,
become SOURCED claims (`origin="event"`) citing every report of the event; the verifier and the
contradiction stages treat them like text claims. A denied rumour is stated as denied, a corrected
price as corrected, with the first figure cited as superseded. No match: text search answers.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ainma.contracts import AccessContext, Citation, Claim, ClaimStatus, MarketEvent
from ainma.pipeline.structured import Routed
from ainma.retrieval.entities import entity_tokens
from ainma.retrieval.streams import query_intent
from ainma.store.base import Store

_KINDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(price|paid|pay|consideration|valuation)\b", re.I), "price"),
    (re.compile(r"\b(rumou?r\w*|bid|offer|interest in|said to|weigh)\b", re.I), "rumour"),
    (
        re.compile(r"\b(chief executive|ceo|appoint\w*|management change)\b", re.I),
        "leadership_change",
    ),
    (re.compile(r"\b(acquir\w*|acquisition\w*|bought|buys?|deals?)\b", re.I), "acquisition"),
)


def asked_kinds(question: str) -> set[str]:
    return {kind for pattern, kind in _KINDS if pattern.search(question)}


def _named(question_tokens: set[str], name: str) -> bool:
    tokens = set(entity_tokens(name))
    return bool(tokens) and tokens <= question_tokens


def route_market(question: str, events: Sequence[MarketEvent]) -> list[MarketEvent]:
    """The events a market question asks for: kind asked, and actor or counterparty named."""
    if query_intent(question) != "market":
        return []
    kinds = asked_kinds(question)
    if not kinds:
        return []
    wanted = set(entity_tokens(question))
    if not wanted:
        return []
    return [
        e
        for e in events
        if e.kind in kinds and (_named(wanted, e.actor) or _named(wanted, e.counterparty))
    ]


def event_text(event: MarketEvent) -> str:
    # no date in the text: the verifier would look for its digits in the quote; the date is on
    # every citation
    when = ""
    if event.kind == "acquisition":
        return f"{event.actor} acquired {event.counterparty}{when}."
    if event.kind == "leadership_change":
        return f"{event.actor} appointed {event.counterparty} as chief executive{when}."
    if event.kind == "price":
        value = f"EUR {event.value_eur_m:g} million" if event.value_eur_m is not None else "a price"
        corrected = (
            ", after a correction of an earlier figure" if event.status == "corrected" else ""
        )
        return f"{event.actor} paid {value} for {event.counterparty}{corrected}{when}."
    if event.status == "denied":
        return (
            f"{event.actor} was reported to weigh an offer for {event.counterparty}, "
            f"then denied it{when}."
        )
    return (
        f"{event.actor} is reported to weigh an offer for {event.counterparty}, unconfirmed{when}."
    )


async def event_claims(
    events: Sequence[MarketEvent], *, store: Store, access: AccessContext, start: int
) -> Routed | None:
    """Claims for the matched events, with the chunks and documents the verifier needs. An event
    whose reports are no longer visible to `access` is left out (the store decides access)."""
    out = Routed(record=None, claims=[])
    for offset, event in enumerate(events):
        cited: list[Citation] = []
        for citation in event.citations:
            chunk = await store.get_chunk(citation.chunk_id, access)
            document = await store.get_document(citation.document_id, access)
            if chunk is None or document is None:
                continue
            out.chunks[chunk.id] = chunk
            out.documents[document.id] = document
            cited.append(citation)
        if not cited:
            continue
        out.claims.append(
            Claim(
                id=f"e{start + offset}",
                text=event_text(event),
                status=ClaimStatus.SOURCED,
                citations=cited,
                origin="event",
            )
        )
    return out if out.claims else None
