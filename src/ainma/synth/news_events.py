"""Second news layer: dated market events with their ground truth (D93).

The first 60 items of the feed are unchanged (they come from their own random stream); this layer
appends items from the stream `news_events`, so earlier truth and results do not move. It plants
what a news-driven analyst must handle:

- `acquisition` echoes: a second outlet repeats an acquisition already in the feed (a duplicate
  of one event, never a second acquisition);
- `leadership_change`: a buyer appoints a chief executive;
- `rumour` then its denial: a buyer is said to weigh an offer for a deal company, then denies it
  (the event's status is `denied`; it must never be reported as a fact);
- `price` then its correction: a first report of the price paid in an acquisition, then a
  correction (the event's value is the corrected one, the first figure is superseded).

Wordings avoid the acquisition verbs of the screening rules on purpose (`buys`, `price for`), so
the screening truth, which counts acquisition reports, is unchanged; consolidating duplicates is
the job of the event layer (`ainma.news`), measured on `truth/news_events.json`.
"""

from __future__ import annotations

from datetime import date, timedelta
from random import Random

from ainma.contracts import DocType
from ainma.synth.common import REFERENCE_DATE, rng_for
from ainma.synth.docs_company import MARK
from ainma.synth.lang import NamePool
from ainma.synth.truthio import NewsItem
from ainma.synth.world import World
from ainma.truth import NewsEventTruth

OUTLETS = ("Trade wire", "Market brief", "Deal monitor")
WINDOW = (date(2024, 7, 1), date(2025, 6, 20))


def _when(rng: Random, start: date = WINDOW[0], end: date = WINDOW[1]) -> date:
    return start + timedelta(days=rng.randrange((end - start).days + 1))


def _item(title: str, body: str, when: date, entity: str) -> NewsItem:
    return NewsItem(
        connector="simulated-news",
        retrieved_on=REFERENCE_DATE,
        title=title,
        url=None,
        published_on=when,
        doc_type=DocType.PRESS_ARTICLE,
        text=f"{MARK} {title}. {body}",
        simulated=True,
        entity=entity,
    )


def build_news_events(
    world: World, feed: list[NewsItem]
) -> tuple[list[NewsItem], list[NewsEventTruth]]:
    """Items to append to `feed` and the truth of every event they report."""
    rng = rng_for(world.params.seed, "news_events")
    names = NamePool(rng_for(world.params.seed, "news_event_names"))
    for company in world.companies:
        names.reserve(company.name)
    for buyer in world.buyers:
        names.reserve(buyer.profile.name.split()[0])
    items: list[NewsItem] = []
    events: list[NewsEventTruth] = []
    by_name = {b.profile.name: b for b in world.buyers}

    def event(**fields: object) -> NewsEventTruth:
        created = NewsEventTruth.model_validate({"id": f"ev_{len(events) + 1:03d}", **fields})
        events.append(created)
        return created

    # 1. acquisitions already in the feed, with an echo from another outlet for one in two
    for original in [i for i in feed if " completes acquisition of " in i.title]:
        buyer_name, target = original.title.split(" completes acquisition of ", 1)
        owner = by_name.get(buyer_name)
        if owner is None or original.published_on is None:
            continue
        titles = [original.title]
        if rng.random() < 0.5:
            outlet = rng.choice(OUTLETS)
            when = original.published_on + timedelta(days=rng.randrange(1, 4))
            title = f"{outlet}: {buyer_name} buys {target}"
            items.append(
                _item(
                    title,
                    f"{buyer_name} took control of {target}, the outlet says.",
                    when,
                    owner.profile.id,
                )
            )
            titles.append(title)
        event(
            kind="acquisition",
            entity=owner.profile.id,
            counterparty=target,
            event_date=original.published_on,
            status="confirmed",
            item_titles=titles,
        )

    # 2. leadership changes at about one buyer in three
    for buyer in world.buyers:
        if rng.random() >= 0.35:
            continue
        person = names.person()
        when = _when(rng)
        title = f"{buyer.profile.name} appoints {person} as chief executive"
        items.append(
            _item(
                title,
                f"{person} takes over as chief executive of {buyer.profile.name}.",
                when,
                buyer.profile.id,
            )
        )
        event(
            kind="leadership_change",
            entity=buyer.profile.id,
            counterparty=person,
            event_date=when,
            status="confirmed",
            item_titles=[title],
        )

    # 3. rumours of an offer for a deal company, two in three denied later
    for company in world.companies:
        buyer = rng.choice(world.buyers)
        when = _when(rng, WINDOW[0], date(2025, 3, 31))
        title = f"{buyer.profile.name} is said to weigh an offer for {company.name}"
        items.append(
            _item(
                title,
                "People familiar with the matter say talks are at an early stage.",
                when,
                company.deal_id,
            )
        )
        titles = [title]
        status = "unconfirmed"
        if rng.random() < 2 / 3:
            later = when + timedelta(days=rng.randrange(3, 30))
            denial = f"{buyer.profile.name} denies interest in {company.name}"
            items.append(
                _item(
                    denial,
                    f"{buyer.profile.name} said it is not in talks about {company.name}.",
                    later,
                    company.deal_id,
                )
            )
            titles.append(denial)
            status = "denied"
        event(
            kind="rumour",
            entity=buyer.profile.id,
            counterparty=company.name,
            event_date=when,
            status=status,
            item_titles=titles,
        )

    # 4. a reported price for one acquisition event in three, corrected one time in two
    for acq in [e for e in list(events) if e.kind == "acquisition"]:
        if rng.random() >= 1 / 3:
            continue
        buyer_name = next(b.profile.name for b in world.buyers if b.profile.id == acq.entity)
        first = float(rng.randrange(40, 400))
        when = acq.event_date + timedelta(days=rng.randrange(5, 20))
        title = f"Price for {buyer_name} and {acq.counterparty} put at EUR {first:.0f} million"
        items.append(
            _item(
                title,
                f"The consideration paid for {acq.counterparty} was EUR {first:.0f} "
                "million, according to people close to the deal.",
                when,
                acq.entity,
            )
        )
        titles = [title]
        value, status = first, "confirmed"
        if rng.random() < 0.5:
            value = float(round(first * rng.choice((0.85, 0.9, 1.1, 1.15))))
            later = when + timedelta(days=rng.randrange(2, 15))
            correction = (
                f"Correction: price for {buyer_name} and {acq.counterparty} was "
                f"EUR {value:.0f} million"
            )
            items.append(
                _item(
                    correction,
                    f"An earlier report gave EUR {first:.0f} million; the "
                    f"consideration was EUR {value:.0f} million.",
                    later,
                    acq.entity,
                )
            )
            titles.append(correction)
            status = "corrected"
        event(
            kind="price",
            entity=acq.entity,
            counterparty=acq.counterparty,
            event_date=when,
            status=status,
            value=value,
            item_titles=titles,
        )
    items.sort(key=lambda i: (i.published_on or REFERENCE_DATE, i.entity, i.title))
    return items, events
