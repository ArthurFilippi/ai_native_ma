"""Two stage buyer screening. Stage 1 reads structured profiles, stage 2 retrieves evidence.

Stage 1 judges every buyer on the prefilter criteria against the request filters. Buyers that do
not fail one are ordered by their prefilter score and the first `stage2_top_n` go to stage 2,
where each applicable deep criterion is evaluated from retrieved, cited passages. Buyers beyond
the cut keep an explicit `unknown` for the deep criteria ("not evaluated"), so coverage tells how
much of the verdict rests on evidence. The final score and rank come from `score_cards` only.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from ainma.contracts import (
    AccessContext,
    BuyerCard,
    BuyerProfile,
    Criterion,
    CriterionResult,
    CriterionStatus,
    ScreeningRequest,
    ScreeningResult,
)
from ainma.kpi import extract_kpis
from ainma.kpi.definitions import DEFAULT_PERIODS
from ainma.kpi.sources import resolve_search
from ainma.llm import LLM
from ainma.screening.criteria import (
    PREFILTER_KEYS,
    ScreeningParams,
    applies_to,
    build_criteria,
)
from ainma.screening.deep import RULES, DealEconomics, DeepContext, sector_terms
from ainma.screening.evidence import EvidenceFinder, SearchFn
from ainma.screening.prefilter import prefilter_results
from ainma.screening.scoring import score_cards
from ainma.screening.universe import resolve_buyers
from ainma.store import Store

_NOT_EVALUATED = "Not evaluated: this buyer is outside the stage 2 top {n}. Never assumed."


async def _deal_economics(
    deal_id: str,
    *,
    store: Store,
    access: AccessContext,
    llm: LLM,
    search: SearchFn,
    params: ScreeningParams,
) -> DealEconomics | None:
    """Latest positive EBITDA found in the deal documents, turned into an indicative size."""
    for period in reversed(DEFAULT_PERIODS):
        (value,) = await extract_kpis(
            deal_id,
            store=store,
            access=access,
            llm=llm,
            periods=[period],
            kpi_ids=["ebitda"],
            search=search,
        )
        if value.value is not None and value.value > 0:
            ev = value.value * params.ev_ebitda_multiple
            return DealEconomics(
                period=period,
                ebitda_eur_m=value.value,
                ev_eur_m=ev,
                cheque_eur_m=ev * params.equity_share_of_ev,
                citations=tuple(value.citations),
            )
    return None


async def _reference_date(
    deal_id: str, *, store: Store, access: AccessContext, params: ScreeningParams
) -> date | None:
    if params.as_of is not None:
        return params.as_of
    dates = [
        c.published_on
        for c in await store.candidates(access, deal_id=deal_id)
        if c.published_on is not None
    ]
    return max(dates) if dates else None


async def _confirm_sector(
    result: CriterionResult, buyer: BuyerProfile, finder: EvidenceFinder, targets: list[str]
) -> CriterionResult:
    """Add a cited sentence to a met `sector_focus` when the buyer's documents state the sector."""
    if result.status is not CriterionStatus.MET:
        return result
    terms = sector_terms(targets)
    pattern = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)
    chunks = await finder.buyer_chunks(buyer, "sector focus invests in portfolio")
    found = finder.find(chunks, pattern)
    if not found:
        return result.model_copy(
            update={"rationale": f"{result.rationale} No textual confirmation was retrieved."}
        )
    return result.model_copy(
        update={
            "rationale": f"{result.rationale} Confirmed in a retrieved passage.",
            "citations": [await finder.cite(found[0])],
        }
    )


def _applicable_deep(buyer: BuyerProfile, criteria: Sequence[Criterion]) -> list[Criterion]:
    out: list[Criterion] = []
    for criterion in criteria:
        if criterion.kind != "deep":
            continue
        wanted_type = applies_to(criterion.key)
        if wanted_type is None or wanted_type is buyer.buyer_type:
            out.append(criterion)
    return out


async def run_screening(
    request: ScreeningRequest,
    *,
    store: Store,
    access: AccessContext,
    llm: LLM,
    buyers: Sequence[BuyerProfile] | None = None,
    params: ScreeningParams | None = None,
    search: SearchFn | None = None,
) -> ScreeningResult:
    """Screen the buyer universe for one deal.

    `buyers` defaults to the store's `list_buyers` when it has one (see `universe`). `params`
    carries the documented assumptions. `search` defaults to `ainma.retrieval.search`.
    Raises `LookupError` when the deal does not exist or is not visible to `access`, and
    `ValueError` for a weight on an unknown criterion or a negative weight.
    """
    params = params or ScreeningParams()
    criteria = build_criteria(request.weights)  # raises on unknown keys
    deal = await store.get_deal(request.deal_id, access)
    if deal is None:
        raise LookupError(f"deal {request.deal_id} not found")
    universe = await resolve_buyers(store, buyers)
    search_fn = search or resolve_search()
    prefilter_criteria = [c for c in criteria if c.key in PREFILTER_KEYS]
    targets = request.filters.sectors or [deal.sector]

    stage1: list[BuyerCard] = []
    for buyer in universe:
        results = prefilter_results(buyer, request.filters, targets)
        passed = all(r.status is not CriterionStatus.NOT_MET for r in results)
        stage1.append(BuyerCard(buyer=buyer, stage1_passed=passed, results=results))
    ordered = score_cards(prefilter_criteria, stage1, {})
    top = [c.buyer.id for c in ordered if c.stage1_passed][: request.stage2_top_n]

    finder = EvidenceFinder(search=search_fn, store=store, access=access, deal_id=deal.id)
    economics = await _deal_economics(
        deal.id, store=store, access=access, llm=llm, search=search_fn, params=params
    )
    as_of = await _reference_date(deal.id, store=store, access=access, params=params)
    target_name = deal.name.split()[-1]

    cards: list[BuyerCard] = []
    for card in stage1:
        if not card.stage1_passed:
            cards.append(card)
            continue
        results = list(card.results)
        if card.buyer.id in top:
            results = [
                await _confirm_sector(r, card.buyer, finder, targets)
                if r.criterion_key == "sector_focus"
                else r
                for r in results
            ]
        ctx = DeepContext(
            buyer=card.buyer,
            finder=finder,
            params=params,
            as_of=as_of,
            economics=economics,
            target_sectors=targets,
            target_name=target_name,
        )
        for criterion in _applicable_deep(card.buyer, criteria):
            if card.buyer.id in top:
                results.append(await RULES[criterion.key](ctx))
            else:
                results.append(
                    CriterionResult(
                        criterion_key=criterion.key,
                        status=CriterionStatus.UNKNOWN,
                        rationale=_NOT_EVALUATED.format(n=request.stage2_top_n),
                    )
                )
        cards.append(card.model_copy(update={"results": results}))

    return ScreeningResult(
        deal_id=deal.id,
        request=request,
        criteria=criteria,
        cards=score_cards(criteria, cards, {}),
    )
