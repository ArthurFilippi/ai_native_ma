"""KPI extraction: retrieve, parse, verify the value inside its quote, compute dependents.

Per KPI and period:

1. `search` retrieves passages for the deal (tables included) through the access filter.
2. The regex reader (mock mode, decision D05) lists candidate values per chunk. The first
   candidate for the KPI and period in rank order is taken.
3. The value must appear inside the quote it is cited with (`value_in_quote`). If it does not, the
   candidate is skipped and the KPI stays `missing` when nothing else verifies.
4. A KPI of kind `compute` is evaluated with the safe evaluator from the values of its
   dependencies, exposing them as `formula_inputs`. When an input is missing, its stated value is
   looked up like an extract KPI instead. Otherwise the KPI is `missing`. Nothing is guessed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ainma.contracts import AccessContext, Chunk, KpiDef, KpiValue
from ainma.kpi.definitions import DEFAULT_PERIODS, KPI_LABELS, kpi_definitions
from ainma.kpi.formula import FormulaError, evaluate_formula, topological_order
from ainma.kpi.parse import Candidate, LabelIndex, last_header, parse_chunk, value_in_quote
from ainma.kpi.scope import ScopedStore
from ainma.kpi.sources import CitationBuilder, SearchFn, resolve_search
from ainma.llm import LLM
from ainma.store import Store

logger = logging.getLogger(__name__)


def _missing(definition: KpiDef, period: str) -> KpiValue:
    return KpiValue(
        kpi_id=definition.id,
        period=period,
        value=None,
        unit=definition.unit,
        status="missing",
    )


class _Extractor:
    def __init__(
        self,
        *,
        deal_id: str,
        store: Store,
        access: AccessContext,
        search: SearchFn,
    ) -> None:
        self._deal_id = deal_id
        self._store = store
        # the deal's own documents only: the buyers' annual reports state revenues of their own
        self._deal_scope = ScopedStore(store, deal_id=deal_id)
        self._access = access
        self._search = search
        self._index = LabelIndex(KPI_LABELS, {d.id: d.unit for d in kpi_definitions()})
        self._citations = CitationBuilder(store, access)
        self._parsed: dict[str, list[Candidate]] = {}
        self._pages: dict[tuple[str, int], list[Chunk]] | None = None

    async def _columns_before(self, chunk: Chunk) -> list[str]:
        """Period columns of the nearest table header before `chunk` on the same page."""
        if self._pages is None:
            self._pages = {}
            for candidate in await self._store.candidates(self._access, deal_id=self._deal_id):
                self._pages.setdefault((candidate.document_id, candidate.page), []).append(
                    candidate
                )
        earlier = [
            c
            for c in self._pages.get((chunk.document_id, chunk.page), [])
            if c.char_start < chunk.char_start
        ]
        for previous in sorted(earlier, key=lambda c: c.char_start, reverse=True):
            columns = last_header(previous.text)
            if columns:
                return columns
        return []

    async def sourced(self, definition: KpiDef, period: str) -> KpiValue | None:
        query = f"{definition.name} {KPI_LABELS[definition.id][0]} {period}"
        hits = await self._search(
            query, store=self._deal_scope, access=self._access, deal_id=self._deal_id
        )
        for hit in hits:
            chunk = hit.chunk
            if chunk.id not in self._parsed:
                columns = await self._columns_before(chunk) if chunk.kind == "table" else []
                self._parsed[chunk.id] = parse_chunk(chunk.text, self._index, columns)
            for candidate in self._parsed[chunk.id]:
                if candidate.kpi_id != definition.id or candidate.period != period:
                    continue
                quote = chunk.text[candidate.start : candidate.end]
                if not value_in_quote(candidate.value, quote):
                    logger.warning(
                        "dropped %s %s: value %s not inside its quote %r",
                        definition.id,
                        period,
                        candidate.value,
                        quote,
                    )
                    continue
                citation = await self._citations.build(chunk, quote)
                return KpiValue(
                    kpi_id=definition.id,
                    period=period,
                    value=candidate.value,
                    unit=definition.unit,
                    status="sourced",
                    citations=[citation],
                )
        return None


def _computed(definition: KpiDef, period: str, known: dict[str, KpiValue]) -> KpiValue | None:
    if definition.formula is None:
        return None
    inputs: dict[str, float] = {}
    for dependency in definition.depends_on:
        value = known.get(dependency)
        if value is None or value.value is None:
            return None
        inputs[dependency] = value.value
    try:
        result = evaluate_formula(definition.formula, inputs)
    except FormulaError as error:
        logger.info("%s %s not computed: %s", definition.id, period, error)
        return None
    return KpiValue(
        kpi_id=definition.id,
        period=period,
        value=result,
        unit=definition.unit,
        status="computed",
        formula_inputs=inputs,
    )


async def extract_kpis(
    deal_id: str,
    *,
    store: Store,
    access: AccessContext,
    llm: LLM,
    periods: Sequence[str] | None = None,
    kpi_ids: Sequence[str] | None = None,
    search: SearchFn | None = None,
) -> list[KpiValue]:
    """One `KpiValue` per definition and period, in definition order then period order.

    `kpi_ids` restricts the result to some KPIs (their dependencies are still read to compute them).

    `llm` is part of the entry point for live providers; the offline reader is a regex routine in
    this package and does not call it. `search` defaults to `ainma.retrieval.search`.
    """
    del llm
    defs = kpi_definitions()
    by_id = {d.id: d for d in defs}
    selected = list(kpi_ids) if kpi_ids is not None else [d.id for d in defs]
    unknown = sorted(set(selected) - set(by_id))
    if unknown:
        raise ValueError(f"unknown KPI ids: {unknown}")
    needed = _with_dependencies(selected, by_id)
    wanted = list(periods) if periods is not None else list(DEFAULT_PERIODS)
    extractor = _Extractor(
        deal_id=deal_id, store=store, access=access, search=search or resolve_search()
    )
    ordered = topological_order(defs)
    values: dict[tuple[str, str], KpiValue] = {}
    for period in wanted:
        known: dict[str, KpiValue] = {}
        for definition in ordered:
            if definition.id not in needed:
                continue
            value = _computed(definition, period, known) if definition.kind == "compute" else None
            if value is None:
                value = await extractor.sourced(definition, period)
            known[definition.id] = value or _missing(definition, period)
        for kpi_id, value in known.items():
            values[(kpi_id, period)] = value
    return [values[(d.id, period)] for d in defs if d.id in set(selected) for period in wanted]


def _with_dependencies(selected: Sequence[str], by_id: dict[str, KpiDef]) -> set[str]:
    needed: set[str] = set()
    pending = list(selected)
    while pending:
        kpi_id = pending.pop()
        if kpi_id not in needed:
            needed.add(kpi_id)
            pending.extend(by_id[kpi_id].depends_on)
    return needed
