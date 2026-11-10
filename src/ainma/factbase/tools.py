"""Typed, parameterised tools over the structured fact base.

The model never writes a query: it may only fill one of the request models below, and code runs
it. The access predicate (the user's deals, or the general layer) is applied inside every tool
before anything is matched or ranked, as the text store does in its SQL.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import Field

from ainma.contracts import AccessContext, Strict
from ainma.factbase.model import Company, FactBaseFile, StructuredFact
from ainma.retrieval.entities import entity_tokens

FACTBASE_PATH = Path("structured") / "factbase.json"

# question metrics (retrieval lexicon keys) that the planted facts name differently
METRIC_ALIASES: dict[str, str] = {
    "fund_size": "aum",
    "production_sites": "plants",
}


class LookupRequest(Strict):
    """`lookup_fact`: the value of one metric for one entity, optionally for one period."""

    metric: str
    entity: str | None = None  # None: the deal's target company
    period: str | None = None  # None: every period


class ComparablesRequest(Strict):
    """`comparables`: one metric for every visible deal company, optionally for one period."""

    metric: str
    period: str | None = None
    sector: str | None = None


class BuyerFilterRequest(Strict):
    """`buyer_facts`: one metric for every visible buyer, optionally within bounds."""

    metric: str
    min_value: float | None = None
    max_value: float | None = None
    buyer_ids: list[str] = Field(default_factory=list)


def canonical_metric(metric: str) -> str:
    return METRIC_ALIASES.get(metric, metric)


class FactBase:
    def __init__(self, data: FactBaseFile) -> None:
        self._facts = list(data.facts)
        self._companies = {c.deal_id: c for c in data.companies}

    @classmethod
    def load(cls, seed_dir: Path) -> FactBase | None:
        path = Path(seed_dir) / FACTBASE_PATH
        if not path.exists():
            return None
        return cls(FactBaseFile.model_validate(json.loads(path.read_text(encoding="utf-8"))))

    @classmethod
    def empty(cls) -> FactBase:
        return cls(FactBaseFile(companies=[], facts=[]))

    def __len__(self) -> int:
        return len(self._facts)

    def _visible(self, access: AccessContext) -> Iterable[StructuredFact]:
        for fact in self._facts:
            if fact.deal_id is None:
                if access.include_general_layer:
                    yield fact
            elif fact.deal_id in access.allowed_deal_ids:
                yield fact

    def company(self, access: AccessContext, deal_id: str | None) -> Company | None:
        if deal_id is None or deal_id not in access.allowed_deal_ids:
            return None
        return self._companies.get(deal_id)

    def lookup(
        self, request: LookupRequest, *, access: AccessContext, deal_id: str | None
    ) -> list[StructuredFact]:
        """Facts of the asked metric about the asked entity (the deal's target by default),
        inside the deal's scope or the general layer; best periods first."""
        metric = canonical_metric(request.metric)
        target = request.entity
        if target is None:
            company = self.company(access, deal_id)
            if company is None:
                return []
            target = company.name
        wanted = set(entity_tokens(target)) or {target.lower()}
        out: list[StructuredFact] = []
        for fact in self._visible(access):
            if fact.metric != metric:
                continue
            if deal_id is not None and fact.deal_id not in (deal_id, None):
                continue
            if request.period is not None and fact.period != request.period:
                continue
            named = set(entity_tokens(fact.entity)) or {fact.entity.lower()}
            if not wanted <= named:
                continue
            out.append(fact)
        return sorted(
            out, key=lambda f: (f.period != request.period, f.period, f.id), reverse=False
        )

    def comparables(
        self, request: ComparablesRequest, *, access: AccessContext
    ) -> list[StructuredFact]:
        """The metric for each visible deal's target company (the comparable set)."""
        metric = canonical_metric(request.metric)
        targets = {c.deal_id: c for c in self._companies.values()}
        out: list[StructuredFact] = []
        for fact in self._visible(access):
            company = targets.get(fact.deal_id or "")
            if company is None or fact.entity != company.name or fact.metric != metric:
                continue
            if request.period is not None and fact.period != request.period:
                continue
            if request.sector is not None and request.sector.lower() not in company.sector.lower():
                continue
            out.append(fact)
        return sorted(out, key=lambda f: (f.deal_id or "", f.period))

    def buyer_facts(
        self, request: BuyerFilterRequest, *, access: AccessContext
    ) -> list[StructuredFact]:
        """The metric for each visible buyer, within the bounds when given."""
        metric = canonical_metric(request.metric)
        out: list[StructuredFact] = []
        for fact in self._visible(access):
            if fact.entity_id is None or fact.metric != metric:
                continue
            if request.buyer_ids and fact.entity_id not in request.buyer_ids:
                continue
            if request.min_value is not None and fact.value < request.min_value:
                continue
            if request.max_value is not None and fact.value > request.max_value:
                continue
            out.append(fact)
        return sorted(out, key=lambda f: (f.entity_id or "", f.period))
