"""Request and result of the `extract_events` task. The mock routine and a live model read the
same request and return the same schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ainma.contracts import Strict


class Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ExtractEventsRequest(Strict):
    text: str  # one news passage


class EventDraft(Lenient):
    kind: Literal["acquisition", "leadership_change", "rumour", "price"]
    stance: Literal["report", "denial", "correction"] = "report"
    actor: str
    counterparty: str
    value_eur_m: float | None = None
    quote: str  # verbatim sentence of the passage that states it


class ExtractEventsResult(Lenient):
    events: list[EventDraft] = Field(default_factory=list)


EXTRACT_EVENTS_PROMPT = """You read one news passage about companies and investors.
List the market events it reports, each with the exact sentence that states it (`quote`, copied
verbatim from the passage). Kinds: `acquisition` (actor acquired counterparty), `leadership_change`
(actor appointed counterparty as chief executive), `rumour` (actor is said to consider an offer
for counterparty), `price` (consideration actor paid for counterparty, `value_eur_m` in EUR
million). `stance`: `report`, `denial` (the actor denies the rumour), `correction` (the passage
corrects an earlier figure). Report only what the passage states. Return JSON only."""
