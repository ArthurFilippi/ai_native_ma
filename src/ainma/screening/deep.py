"""Stage 2: one rule per criterion over retrieved evidence. Deterministic, no LLM.

Principle: a criterion without evidence is `unknown`. A rule only returns `met` or `not_met` when a
cited passage (or a cited deal figure) supports the verdict, and the rationale says which numbers
were used and which of them are documented parameters (`ScreeningParams`) rather than sources.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from ainma.contracts import (
    BuyerProfile,
    Chunk,
    Citation,
    CriterionResult,
    CriterionStatus,
)
from ainma.kpi.parse import find_money, parse_number
from ainma.screening.criteria import ScreeningParams
from ainma.screening.evidence import Evidence, EvidenceFinder

_I = re.IGNORECASE
_MONTHS = "|".join(calendar.month_name[1:])
_SIZE = re.compile(
    r"total commitments|commitments of|assets under management|\bAUM\b|fund size|"
    r"market capitali[sz]ation|market cap\b",
    _I,
)
_YEAR = r"(?:19|20)\d{2}"
# Ways a fund document states when new investments stop (a year, with a month sometimes).
_INVEST_END = (
    re.compile(
        r"investment period[^.\n]{0,80}?\b(?:ends?|ending|expires?|expiring|"
        r"runs?\s+(?:until|through|to)|until|through)\s+(?:in\s+|at\s+the\s+end\s+of\s+)?"
        rf"(?:(?P<month>{_MONTHS})\s+)?(?P<year>{_YEAR})",
        _I,
    ),
    re.compile(
        r"new\s+(?:platform\s+)?(?:investments?|deals?|commitments?)[^.\n]{0,60}?"
        rf"\b(?:until|through|up\s+to)\s+(?:(?P<month>{_MONTHS})\s+)?(?P<year>{_YEAR})",
        _I,
    ),
    re.compile(rf"investment period end[^.\n|:]{{0,12}}[:|]\s*(?P<month>)(?P<year>{_YEAR})", _I),
)
_NO_INVEST_END = re.compile(
    r"permanent capital|(?:without|no)\s+(?:a\s+)?fixed\s+investment\s+period|evergreen", _I
)
_INVEST_LENGTH = re.compile(r"(?P<n>\d+(?:\.\d+)?)[- ]year investment period", _I)
_ACQUISITION = re.compile(
    r"\b(?:acquired(?!\s+by)|acquires|acquiring|acquisition of|completed the acquisition|"
    r"agreed to acquire|has bought|bought|took over|takes over|add-on acquisition)\b",
    _I,
)
_PCT = r"(?:%|percent|per\s+cent)"
_SHARE = re.compile(
    rf"market share[^.\n]{{0,60}}?(?P<a>\d+(?:[.,]\d+)?)\s*{_PCT}"
    rf"|(?P<b>\d+(?:[.,]\d+)?)\s*{_PCT}\s+(?:of\s+the\s+[\w\s-]{{0,30}}?)?market share"
    rf"|\b(?:controls|holds|commands|accounts\s+for)\s+(?P<c>\d+(?:[.,]\d+)?)\s*{_PCT}\s+of\s+"
    r"(?:the\s+)?[\w\s-]{0,40}?\b(?:sales|market|segment)\b",
    _I,
)
_CONSTRAINT = re.compile(
    r"state[- ]owned|state ownership|government[- ]owned|government (?:stake|ownership)|"
    r"owned by (?:the|a) (?:state|government)|state shareholders?|"
    r"sovereign wealth|sovereign fund|golden share|"
    r"foreign investment (?:screening|control|review)|\bFDI\b|"
    r"national security|exposure to defen[cs]e|"
    r"defen[cs]e (?:contractor|contracts?|exposure|sector|business|revenue|activities)",
    _I,
)
# Explicit absence of a constraint. `privately held` is not one: it says the shares are not
# traded, not who owns them (a state owned company can be privately held).
_CLEAN_OWNERSHIP = re.compile(r"privately[- ]owned|private ownership|family[- ]owned", _I)
_NEGATION = re.compile(r"\b(?:no|not|without|never|free\s+of)\b[^.\n]{0,30}$", _I)
_EV_CUE = re.compile(r"enterprise value|cash[- ]free(?:,)? and debt[- ]free", _I)
_EQUITY_CUE = re.compile(r"equity value|shareholders would receive", _I)


@dataclass(frozen=True)
class DealEconomics:
    """The indicative size of the transaction. The enterprise value and the equity cheque are
    the values the deal documents state when they do; otherwise they come from the deal's EBITDA
    and the documented parameters. `ev_basis` and `cheque_basis` say which, in words, and
    `citations` are the sources of the sourced numbers."""

    ev_eur_m: float
    cheque_eur_m: float
    ev_basis: str
    cheque_basis: str
    citations: tuple[Citation, ...]


async def _stated_amount(
    finder: EvidenceFinder, chunks: list[Chunk], cue: re.Pattern[str]
) -> tuple[Evidence, float] | None:
    """The first amount written after the cue in a sentence of the deal documents, with the
    sentence as evidence."""
    for evidence in finder.find(chunks, cue):
        tail = evidence.quote[evidence.match.start() - _quote_start(evidence) :]
        amounts = find_money(tail)
        if amounts:
            return evidence, amounts[0][2]
    return None


def _quote_start(evidence: Evidence) -> int:
    return evidence.chunk.text.find(evidence.quote)


async def stated_valuation(finder: EvidenceFinder, params: ScreeningParams) -> DealEconomics | None:
    """The deal's enterprise value and equity value as the deal documents state them (CIM,
    executed SPA; a superseded draft is not read). Only an enterprise value is required: without
    a stated equity value the cheque is the documented share of it."""
    chunks = await finder.deal_chunks(
        "enterprise value equity value purchase price priced cash-free debt-free "
        "shareholders would receive for their shares"
    )
    ev = await _stated_amount(finder, chunks, _EV_CUE)
    if ev is None:
        return None
    equity = await _stated_amount(finder, chunks, _EQUITY_CUE)
    citations = [await finder.cite(ev[0])]
    ev_basis = f"Deal enterprise value EUR {ev[1]:g}m (sourced)"
    if equity is not None:
        citations.append(await finder.cite(equity[0]))
        cheque = equity[1]
        cheque_basis = f"deal equity value EUR {equity[1]:g}m (sourced) as the equity cheque"
    else:
        cheque = ev[1] * params.equity_share_of_ev
        cheque_basis = f"equity cheque at {params.equity_share_of_ev:.0%} of EV (parameter)"
    return DealEconomics(ev[1], cheque, ev_basis, cheque_basis, tuple(citations))


class DeepContext:
    def __init__(
        self,
        *,
        buyer: BuyerProfile,
        finder: EvidenceFinder,
        params: ScreeningParams,
        as_of: date | None,
        economics: DealEconomics | None,
        target_sectors: list[str],
        target_name: str,
    ) -> None:
        self.buyer = buyer
        self.finder = finder
        self.params = params
        self.as_of = as_of
        self.economics = economics
        self.target_sectors = target_sectors
        self.target_name = target_name
        self._acquisitions: list[Evidence] | None = None

    def in_target_sector(self, evidence: Evidence) -> bool:
        """The acquisition sentence (and the sentence about `the target` after it) names the
        target's sector. The buyer's own name is removed first: `Draix Industries` is not an
        industrial company."""
        quote = evidence.quote.replace(self.buyer.name, " ")
        return sector_regex(self.target_sectors).search(quote) is not None

    async def acquisitions(self) -> list[Evidence]:
        """Dated passages reporting an acquisition by the buyer, one per document, newest first.

        When several passages of a document report it (a news item has its title and its body in
        separate chunks), the one that places the target in the deal's sector is kept.
        """
        if self._acquisitions is None:
            chunks = await self.finder.buyer_chunks(
                self.buyer, "acquisition acquired completed the acquisition of"
            )
            by_document: dict[str, list[Evidence]] = {}
            for found_one in self.finder.find(chunks, _ACQUISITION):
                chunk = found_one.chunk
                if chunk.published_on is None:
                    continue
                if self.as_of is not None and chunk.published_on > self.as_of:
                    continue
                evidence = self.finder.with_target_sentence(found_one)
                by_document.setdefault(chunk.document_id, []).append(evidence)
            found = [
                next((e for e in group if self.in_target_sector(e)), group[0])
                for group in by_document.values()
            ]
            found.sort(key=lambda e: (e.chunk.published_on or date.min, e.chunk.id), reverse=True)
            self._acquisitions = found
        return self._acquisitions


Rule = Callable[[DeepContext], Awaitable[CriterionResult]]


def _result(
    key: str,
    status: CriterionStatus,
    rationale: str,
    citations: list[Citation] | None = None,
    *,
    conflicting: bool = False,
) -> CriterionResult:
    return CriterionResult(
        criterion_key=key,
        status=status,
        rationale=rationale,
        citations=citations or [],
        conflicting_evidence=conflicting,
    )


def _unknown(key: str, rationale: str) -> CriterionResult:
    return _result(key, CriterionStatus.UNKNOWN, rationale)


def _months_between(earlier: date, later: date) -> float:
    return (later - earlier).days / 30.4375


async def _size_evidence(
    ctx: DeepContext, topic: str, own_size: float
) -> tuple[list[Citation], bool]:
    """Passages stating the buyer's size. A passage with a different amount is flagged as
    conflicting evidence, the structured profile figure stays the one used in the ratio."""
    chunks = await ctx.finder.buyer_chunks(ctx.buyer, topic)
    agreeing: list[Evidence] = []
    differing: list[Evidence] = []
    for evidence in ctx.finder.find(chunks, _SIZE):
        amounts = [value for _, _, value in find_money(evidence.quote)]
        if not amounts:
            continue
        if any(abs(a - own_size) <= 0.01 * own_size for a in amounts):
            agreeing.append(evidence)
        else:
            differing.append(evidence)
    shown = agreeing[:1] + differing[:1]
    return [await ctx.finder.cite(e) for e in shown], bool(differing)


async def ticket_fit(ctx: DeepContext) -> CriterionResult:
    key, params, economics = "ticket_fit", ctx.params, ctx.economics
    if economics is None:
        return _unknown(
            key,
            "No deal value or EBITDA was found in the deal sources: no indicative cheque can "
            "be sized.",
        )
    share = economics.cheque_eur_m / ctx.buyer.size_eur_m
    if share < params.ticket_not_met_below:
        status, band = CriterionStatus.NOT_MET, f"below the {params.ticket_not_met_below:.0%} floor"
    elif share > params.ticket_not_met_above:
        status, band = CriterionStatus.NOT_MET, f"above the {params.ticket_not_met_above:.0%} cap"
    elif params.ticket_healthy_low <= share <= params.ticket_healthy_high:
        status = CriterionStatus.MET
        band = (
            f"inside the healthy {params.ticket_healthy_low:.0%} to "
            f"{params.ticket_healthy_high:.0%} band"
        )
    else:
        status = CriterionStatus.MET
        band = (
            f"inside the {params.ticket_not_met_below:.0%} to {params.ticket_not_met_above:.0%} "
            "limits but outside the healthy band"
        )
    cites, conflicting = await _size_evidence(
        ctx, "fund size total commitments assets under management", ctx.buyer.size_eur_m
    )
    size_note = (
        "fund size from the structured profile, confirmed by a cited passage"
        if cites and not conflicting
        else "fund size from the structured profile, no confirming passage found"
        if not cites
        else "fund size from the structured profile, a cited passage states another amount"
    )
    rationale = (
        f"{economics.ev_basis}; {economics.cheque_basis} = EUR {economics.cheque_eur_m:g}m, "
        f"which is {share:.1%} of EUR {ctx.buyer.size_eur_m:g}m ({size_note}): {band}."
    )
    return _result(key, status, rationale, [*economics.citations, *cites], conflicting=conflicting)


async def ev_ratio(ctx: DeepContext) -> CriterionResult:
    key, params, economics = "ev_ratio", ctx.params, ctx.economics
    if economics is None:
        return _unknown(
            key,
            "No deal value or EBITDA was found in the deal sources: no indicative EV can be sized.",
        )
    ratio = economics.ev_eur_m / ctx.buyer.size_eur_m
    if ratio > params.ev_ratio_not_met_above:
        status, band = (
            CriterionStatus.NOT_MET,
            f"above {params.ev_ratio_not_met_above:.0%}, rarely feasible",
        )
    elif ratio > params.ev_ratio_transformational:
        status, band = (
            CriterionStatus.MET,
            f"transformational (above {params.ev_ratio_transformational:.0%}), feasible but heavy",
        )
    else:
        status, band = CriterionStatus.MET, "within a normal range for the buyer"
    cites, conflicting = await _size_evidence(
        ctx, "market capitalisation market cap", ctx.buyer.size_eur_m
    )
    rationale = (
        f"{economics.ev_basis} is {ratio:.1%} of the buyer's market "
        f"capitalisation of EUR {ctx.buyer.size_eur_m:g}m (used as a proxy for buyer EV): {band}."
    )
    return _result(key, status, rationale, [*economics.citations, *cites], conflicting=conflicting)


def _end_of_investment_period(match: re.Match[str]) -> date:
    year = int(match.group("year"))
    month_name = match.group("month")
    if not month_name:
        return date(year, 7, 1)  # only the year is stated: mid-year
    month = list(calendar.month_name).index(month_name.capitalize())
    return date(year, month, calendar.monthrange(year, month)[1])


async def fund_lifecycle(ctx: DeepContext) -> CriterionResult:
    key, params = "fund_lifecycle", ctx.params
    if ctx.as_of is None:
        return _unknown(key, "No reference date is available to measure the remaining period.")
    chunks = await ctx.finder.buyer_chunks(
        ctx.buyer,
        "investment period new platform deals investments until fund vintage permanent capital",
    )
    ends = ctx.finder.find(chunks, _INVEST_END)
    if not ends:
        permanent = ctx.finder.find(chunks, _NO_INVEST_END)
        if permanent:
            return _result(
                key,
                CriterionStatus.MET,
                "A source describes a permanent capital structure without a fixed investment "
                "period: there is no date by which new investments must stop.",
                [await ctx.finder.cite(permanent[0])],
            )
    end: date | None = None
    chosen: Evidence | None = None
    conflicting = False
    if ends:
        chosen = ends[0]
        end = _end_of_investment_period(chosen.match)
        conflicting = any(_end_of_investment_period(e.match) != end for e in ends[1:])
    elif ctx.buyer.fund_vintage_year is not None:
        lengths = ctx.finder.find(chunks, _INVEST_LENGTH)
        if lengths:
            chosen = lengths[0]
            end = date(ctx.buyer.fund_vintage_year + round(float(chosen.match.group("n"))), 7, 1)
    if end is None or chosen is None:
        return _unknown(key, "No source states when the investment period ends.")
    remaining = (end - ctx.as_of).days / 365.25
    met = remaining >= params.min_investment_years_remaining
    rationale = (
        f"The investment period ends {end.isoformat()}, {remaining:.1f} years after "
        f"{ctx.as_of.isoformat()}; at least {params.min_investment_years_remaining:g} years "
        "(parameter) are needed to deploy."
    )
    if conflicting:
        rationale += " Sources disagree on the end date: the highest ranked passage is used."
    return _result(
        key,
        CriterionStatus.MET if met else CriterionStatus.NOT_MET,
        rationale,
        [await ctx.finder.cite(chosen)],
        conflicting=conflicting,
    )


_STOP_WORDS = frozenset({"and", "for", "the", "of"})
_STEM = 6


def sector_regex(sectors: list[str]) -> re.Pattern[str]:
    """A pattern matching a sector wording: every word of a sector (by its first letters) in
    order, with up to two words between them, or the two words of a pair in reverse order.
    `industrial_components` finds `industrial components` but not `Industries` alone."""
    alternatives: list[str] = []
    for sector in sectors:
        stems = [
            re.escape(w[:_STEM])
            for w in re.findall(r"[a-z]+", sector.lower())
            if w not in _STOP_WORDS and len(w) >= 3
        ]
        if not stems:
            continue
        gap = r"\w*\W+(?:\w+\W+){0,2}?"
        alternatives.append(rf"\b{gap.join(stems)}\w*")
        if len(stems) == 2:
            alternatives.append(rf"\b{gap.join(reversed(stems))}\w*")
    if not alternatives:
        return re.compile(r"(?!x)x")
    return re.compile("|".join(alternatives), _I)


async def recent_activity(ctx: DeepContext) -> CriterionResult:
    key, params = "recent_activity", ctx.params
    acquisitions = await ctx.acquisitions()
    if not acquisitions:
        return _unknown(key, "No dated source reports an acquisition by this buyer.")
    if ctx.as_of is None:
        return _unknown(key, "No reference date is available to date the acquisitions.")
    similar = [
        e
        for e in acquisitions
        if e.chunk.published_on is not None
        and _months_between(e.chunk.published_on, ctx.as_of) <= params.recent_activity_months
        and ctx.in_target_sector(e)
    ]
    if similar:
        shown = similar[:3]
        return _result(
            key,
            CriterionStatus.MET,
            f"{len(similar)} dated source(s) report an acquisition in the target's sector within "
            f"the last {params.recent_activity_months} months before {ctx.as_of.isoformat()}.",
            [await ctx.finder.cite(e) for e in shown],
        )
    newest = acquisitions[0]
    return _result(
        key,
        CriterionStatus.NOT_MET,
        f"Acquisitions are reported, but none in the target's sector within the last "
        f"{params.recent_activity_months} months before {ctx.as_of.isoformat()}; the newest is "
        f"dated {newest.chunk.published_on}.",
        [await ctx.finder.cite(newest)],
    )


async def integration_bandwidth(ctx: DeepContext) -> CriterionResult:
    key, params = "integration_bandwidth", ctx.params
    acquisitions = await ctx.acquisitions()
    if not acquisitions:
        return _unknown(key, "No dated source reports an acquisition by this buyer.")
    if ctx.as_of is None:
        return _unknown(key, "No reference date is available to date the acquisitions.")
    recent = [
        e
        for e in acquisitions
        if e.chunk.published_on is not None
        and _months_between(e.chunk.published_on, ctx.as_of) <= params.integration_window_months
    ]
    met = len(recent) <= params.max_recent_acquisitions
    return _result(
        key,
        CriterionStatus.MET if met else CriterionStatus.NOT_MET,
        f"{len(recent)} acquisition report(s) in dated sources within the last "
        f"{params.integration_window_months} months (counted per document, so a lower bound); "
        f"the limit is {params.max_recent_acquisitions} (parameter).",
        [await ctx.finder.cite(e) for e in recent[:3]],
    )


def _shares(evidence: list[Evidence]) -> list[tuple[Evidence, float]]:
    shares: list[tuple[Evidence, float]] = []
    for e in evidence:
        token = e.match.group("a") or e.match.group("b") or e.match.group("c")
        if token:
            shares.append((e, parse_number(token)))
    return shares


async def antitrust(ctx: DeepContext) -> CriterionResult:
    key, params = "antitrust", ctx.params
    buyer_chunks = await ctx.finder.buyer_chunks(ctx.buyer, "market share")
    buyer_share = _shares(ctx.finder.find(buyer_chunks, _SHARE))
    if not buyer_share:
        return _unknown(key, "No market share data was found for this buyer: not evaluated.")
    target_chunks = await ctx.finder.deal_chunks(f"{ctx.target_name} market share")
    mention = re.compile(rf"\b{re.escape(ctx.target_name)}\b", _I)
    target_share = _shares(
        [e for e in ctx.finder.find(target_chunks, _SHARE) if mention.search(e.quote)]
    )
    own, own_value = buyer_share[0]
    cites = [await ctx.finder.cite(own)]
    threshold = params.antitrust_combined_share_pct
    if not target_share:
        if own_value >= threshold:
            return _result(
                key,
                CriterionStatus.NOT_MET,
                f"The buyer alone holds {own_value:g}% market share, at or above the "
                f"{threshold:g}% combined-share flag (parameter); the target's share is unknown.",
                cites,
            )
        return _unknown(
            key,
            f"The buyer holds {own_value:g}% market share but no source gives the target's "
            "share, so the combined share cannot be established.",
        )
    other, other_value = target_share[0]
    cites.append(await ctx.finder.cite(other))
    combined = own_value + other_value
    met = combined < threshold
    return _result(
        key,
        CriterionStatus.MET if met else CriterionStatus.NOT_MET,
        f"Combined market share {own_value:g}% + {other_value:g}% = {combined:g}%, "
        f"{'below' if met else 'at or above'} the {threshold:g}% flag (parameter). "
        "Market definition and credible alternatives are not assessed.",
        cites,
    )


def _negated(evidence: Evidence) -> bool:
    return _NEGATION.search(evidence.chunk.text[: evidence.match.start()]) is not None


async def regulatory_fdi(ctx: DeepContext) -> CriterionResult:
    key = "regulatory_fdi"
    chunks = await ctx.finder.buyer_chunks(
        ctx.buyer,
        "state ownership shareholders sovereign wealth defense defence exposure contracts "
        "foreign investment privately owned",
    )
    found = ctx.finder.find(chunks, _CONSTRAINT)
    # a negated constraint ("has no state shareholders") is an explicit clean statement
    constraints = [e for e in found if not _negated(e)]
    clean = [e for e in found if _negated(e)] + ctx.finder.find(chunks, _CLEAN_OWNERSHIP)
    if constraints:
        return _result(
            key,
            CriterionStatus.NOT_MET,
            "A source reports a sovereignty, state ownership, defense or foreign investment "
            "constraint."
            + (" Another source states a clean ownership: sources disagree." if clean else ""),
            [await ctx.finder.cite(constraints[0])],
            conflicting=bool(clean),
        )
    if clean:
        return _result(
            key,
            CriterionStatus.MET,
            "A source states a private ownership or the absence of state ownership, and no "
            "constraint was found.",
            [await ctx.finder.cite(clean[0])],
        )
    return _unknown(key, "No source mentions ownership, sovereignty or defense exposure.")


RULES: dict[str, Rule] = {
    "ticket_fit": ticket_fit,
    "ev_ratio": ev_ratio,
    "fund_lifecycle": fund_lifecycle,
    "recent_activity": recent_activity,
    "integration_bandwidth": integration_bandwidth,
    "antitrust": antitrust,
    "regulatory_fdi": regulatory_fdi,
}
