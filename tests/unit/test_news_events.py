"""News events: duplicates merge, a denial makes a rumour `denied`, a correction replaces a price
and keeps the first figure as superseded; every report is cited verbatim (D94)."""

from __future__ import annotations

from datetime import date

from ainma.connectors.run import ingest_from
from ainma.contracts import BuyerProfile, BuyerType, Deal, Membership, Role, User
from ainma.llm import build_mock_llm
from ainma.news import extract_events_rules, market_events
from ainma.store import SqliteStore
from ainma.truth import NewsFeedItem

DEAL = "deal_x"


def _item(title: str, body: str, day: int) -> NewsFeedItem:
    return NewsFeedItem(
        connector="simulated-news",
        retrieved_on=date(2025, 6, 30),
        title=title,
        published_on=date(2025, 1, day),
        text=f"{title}. {body}",
        entity="buyer_1",
    )


ITEMS = [
    _item("Orvane Capital completes acquisition of Tessil Works", "It is an add-on.", 2),
    _item("Trade wire: Orvane Capital buys Tessil Works", "The outlet says so.", 4),
    _item("Price for Orvane Capital and Tessil Works put at EUR 120 million", "Sources say.", 8),
    _item(
        "Correction: price for Orvane Capital and Tessil Works was EUR 102 million", "Fixed.", 12
    ),
    _item("Orvane Capital is said to weigh an offer for Brisk Valves", "Early talks.", 14),
    _item("Orvane Capital denies interest in Brisk Valves", "No talks.", 20),
    _item("Orvane Capital appoints Lena Varo as chief executive", "Effective now.", 22),
]


class _Feed:
    name = "test-feed"

    async def entities(self) -> list[str]:
        return ["buyer_1"]

    async def fetch(self, *, entity: str, since: date) -> list[NewsFeedItem]:
        return ITEMS


def test_rules_read_each_headline_once() -> None:
    result = extract_events_rules(ITEMS[2].text)
    (draft,) = result.events
    assert (draft.kind, draft.stance, draft.value_eur_m) == ("price", "report", 120.0)
    assert draft.quote in ITEMS[2].text


async def test_reports_are_consolidated_and_cited() -> None:
    store = await SqliteStore.open(":memory:")
    await store.put_deal(Deal(id=DEAL, name="Project X", sector="industrial"))
    await store.put_user(User(id="u", name="Lead"))
    await store.put_user(User(id="nobody", name="Outsider"))
    await store.put_membership(Membership(deal_id=DEAL, user_id="u", role=Role.LEAD))
    await store.put_buyer(
        BuyerProfile(
            id="buyer_1",
            name="Orvane Capital",
            buyer_type=BuyerType.FINANCIAL,
            sectors=["industrial"],
            geographies=["DACH"],
            size_eur_m=900.0,
        )
    )
    await ingest_from(_Feed(), ["buyer_1"], DEAL, store, date.min)  # type: ignore[arg-type]
    access = await store.access_for("u")
    events = await market_events(DEAL, store=store, access=access, llm=build_mock_llm())
    by_kind = {e.kind: e for e in events}
    assert len(events) == 4
    acquisition = by_kind["acquisition"]
    assert acquisition.n_reports == 2 and len(acquisition.citations) == 2  # one event, two outlets
    assert acquisition.buyer_id == "buyer_1" and acquisition.event_date == date(2025, 1, 2)
    price = by_kind["price"]
    assert price.status == "corrected" and price.value_eur_m == 102.0
    assert len(price.superseded_citations) == 1 and "120" in price.superseded_citations[0].quote
    assert by_kind["rumour"].status == "denied"
    assert by_kind["leadership_change"].counterparty == "Lena Varo"
    for event in events:
        for citation in event.citations:
            page = await store.get_page(citation.document_id, citation.page, access)
            assert (
                page is not None and page[citation.char_start : citation.char_end] == citation.quote
            )
    outsider = await store.access_for("nobody")
    try:
        await market_events(DEAL, store=store, access=outsider, llm=build_mock_llm())
    except LookupError:
        pass
    else:
        raise AssertionError("a non member must not read the deal's events")
    await store.close()


async def test_a_market_question_is_answered_from_the_events() -> None:
    """D102: the denied rumour is stated as denied, cited to its reports, and verified."""
    from ainma.pipeline import PipelineConfig, ask
    from ainma.pipeline.events_route import route_market

    store = await SqliteStore.open(":memory:")
    await store.put_deal(Deal(id=DEAL, name="Project X", sector="industrial"))
    await store.put_user(User(id="u", name="Lead"))
    await store.put_membership(Membership(deal_id=DEAL, user_id="u", role=Role.LEAD))
    await ingest_from(_Feed(), ["buyer_1"], DEAL, store, date.min)  # type: ignore[arg-type]
    access = await store.access_for("u")
    events = await market_events(DEAL, store=store, access=access, llm=build_mock_llm())
    question = "Is Orvane Capital reported to bid for Brisk Valves?"
    assert [e.kind for e in route_market(question, events)] == ["rumour"]
    answer = await ask(
        question,
        store=store,
        access=access,
        deal_id=DEAL,
        llm=build_mock_llm(),
        config=PipelineConfig(answers_log=None),
        events=events,
    )
    (claim,) = [c for c in answer.claims if c.origin == "event"]
    assert "denied" in claim.text and len(claim.citations) == 2
    assert claim.verification is not None and claim.verification.supported
    off = await ask(
        "What is the revenue of Orvane Capital?",
        store=store,
        access=access,
        deal_id=DEAL,
        llm=build_mock_llm(),
        config=PipelineConfig(answers_log=None),
        events=events,
    )
    assert all(c.origin != "event" for c in off.claims)  # not a market question
    await store.close()
