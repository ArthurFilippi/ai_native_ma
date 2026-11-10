"""Fact book and document builder: states facts in prose or tables and records where."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from random import Random

from ainma.synth.common import Params
from ainma.synth.docspec import Cell, DocSpec, Part
from ainma.synth.lang import (
    METRICS,
    fmt_value,
    render_sentence,
)


@dataclass
class FactDraft:
    id: str
    deal_id: str | None
    entity: str
    metric: str
    period: str
    value: float
    unit: str
    doc_id: str
    keywords: list[str]


@dataclass
class FactBook:
    facts: dict[str, FactDraft] = field(default_factory=dict)
    _index: dict[tuple[str, str, str, str], str] = field(default_factory=dict)

    def get_or_create(
        self, doc: DocSpec, entity: str, metric: str, period: str, value: float
    ) -> str:
        key = (doc.id, entity, metric, period)
        existing = self._index.get(key)
        if existing is not None:
            if abs(self.facts[existing].value - value) > 1e-9:
                raise ValueError(f"{doc.id}: conflicting values for {key}")
            return existing
        m = METRICS[metric]
        fact_id = f"fact_{len(self.facts) + 1:05d}"
        self.facts[fact_id] = FactDraft(
            id=fact_id,
            deal_id=doc.deal_id,
            entity=entity,
            metric=metric,
            period=period,
            value=value,
            unit=m.unit,
            doc_id=doc.id,
            keywords=m.keywords(period),
        )
        self._index[key] = fact_id
        return fact_id

    def lookup(self, doc_id: str, entity: str, metric: str, period: str) -> FactDraft | None:
        found = self._index.get((doc_id, entity, metric, period))
        return self.facts[found] if found else None


def prev_period(period: str) -> str:
    return f"FY{int(period.removeprefix('FY')) - 1}"


# Press phrasing: hedged, rounded, third person. Used for the trade press layer.
PRESS_TEMPLATES: dict[str, tuple[str, ...]] = {
    "revenue": (
        "{S} booked roughly {V} of revenue in {Y}.",
        "Trade sources put {S} revenue for {Y} at about {V}.",
    ),
    "ebitda": (
        "{S} is said to have earned roughly {V} of EBITDA in {Y}.",
        "Analysts estimate {S} EBITDA for {Y} at around {V}.",
    ),
    "headcount": (
        "{S} is believed to employ around {V} people.",
        "The company reportedly had a workforce of about {V} at the end of {Y}.",
    ),
    "aum": (
        "{S} is reported to manage roughly {V}.",
        "Industry estimates put the assets of {S} at about {V} in {Y}.",
    ),
    "market_cap": (
        "{S} was valued at roughly {V} by the market in {Y}.",
        "The stock market capitalisation of {S} was reported near {V} in {Y}.",
    ),
}


class DocWriter:
    """Adds facts to one document. `rng` is a stream private to this document."""

    def __init__(self, spec: DocSpec, book: FactBook, rng: Random, params: Params) -> None:
        self.spec = spec
        self.book = book
        self.rng = rng
        self.params = params

    def choose_form(self) -> str:
        return "par" if self.rng.random() < self.params.paraphrase_rate else "lit"

    def stated(
        self,
        entity: str,
        metric: str,
        period: str,
        value: float,
        *,
        form: str | None = None,
        prev: float | None = None,
        with_entity: bool = False,
        force: int | None = None,
        style: str | None = None,
    ) -> Part:
        """One sentence stating `metric` (and the previous period when the template does)."""
        m = METRICS[metric]
        chosen = form or self.choose_form()
        prev_arg = (prev_period(period), prev) if prev is not None else None
        text, used_prev = render_sentence(
            m,
            entity=entity,
            period=period,
            value=value,
            form=chosen,
            rng=self.rng,
            prev=prev_arg,
            with_entity=with_entity,
            force=force,
            value_style=style,
        )
        ids = [self.book.get_or_create(self.spec, entity, metric, period, value)]
        if used_prev and prev is not None:
            ids.append(
                self.book.get_or_create(self.spec, entity, metric, prev_period(period), prev)
            )
        return Part(text, tuple(ids))

    def ticket(self, entity: str, low: float, high: float, form: str | None = None) -> Part:
        m = METRICS["ticket_min"]
        chosen = form or self.choose_form()
        template = (m.lit if chosen == "lit" else m.par)[0]
        text = template.format(
            V=fmt_value("money", low, None, "mn"), V2=fmt_value("money", high, None, "mn")
        )
        ids = (
            self.book.get_or_create(self.spec, entity, "ticket_min", "static", low),
            self.book.get_or_create(self.spec, entity, "ticket_max", "static", high),
        )
        return Part(text, ids)

    def press(
        self,
        entity: str,
        short: str,
        metric: str,
        period: str,
        value: float,
        style: str = "int",
        force: int | None = None,
    ) -> Part:
        templates = PRESS_TEMPLATES[metric]
        template = templates[force if force is not None else self.rng.randrange(len(templates))]
        m = METRICS[metric]
        text = template.format(
            S=short, Y=period.removeprefix("FY"), V=fmt_value(m.vkind, value, None, style)
        )
        fid = self.book.get_or_create(self.spec, entity, metric, period, value)
        return Part(text, (fid,))

    def footnote(self, entity: str, metric: str, period: str, value: float, number: int) -> Part:
        m = METRICS[metric]
        text = f"Note {number}: " + m.foot.format(P=period, V=fmt_value(m.vkind, value, None, "mn"))
        fid = self.book.get_or_create(self.spec, entity, metric, period, value)
        return Part(text, (fid,))

    def fact_table(
        self,
        entity: str,
        header: list[Cell],
        rows: Sequence[tuple[str, str | None, Sequence[float]]],
        periods: list[str],
    ) -> None:
        """Table whose rows with a metric plant one fact per period (quote is the whole row)."""
        table_rows: list[list[Cell]] = [header]
        facts: dict[int, tuple[str, ...]] = {}
        for label, metric, values in rows:
            if metric is not None:
                ids = tuple(
                    self.book.get_or_create(self.spec, entity, metric, p, float(v))
                    for p, v in zip(periods, values, strict=True)
                )
                facts[len(table_rows)] = ids
            table_rows.append([label, *values])
        self.spec.table(table_rows, facts)
