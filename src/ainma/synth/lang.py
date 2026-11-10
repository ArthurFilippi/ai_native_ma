"""Phrasing of facts: metric registry, number formats, sentence templates, fictional names.

Every metric has several literal phrasings ("lit"), paraphrases that avoid the canonical words
("par"), a table row label, a footnote form, a claim form and question templates. Everything is
ASCII and fictional. Templates are plain `str.format` strings with these fields: E entity,
P period (FY2024), PL long period, V value phrase, PP and VP previous period and value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

# ---- number formats -----------------------------------------------------------------------


def fmt_money(value: float, rng: Random | None = None, style: str | None = None) -> str:
    """EUR amount from a value in EUR m. Styles: `mn` (EUR 182.4 million), `m` (EUR 182.4m),
    `bn` (EUR 4.2 billion, only for round values), `int` (EUR 179 million, whole values)."""
    if style is None:
        options = ["mn", "mn", "m"]
        if value >= 1000 and round(value) % 50 == 0:
            options.append("bn")
        style = options[rng.randrange(len(options))] if rng else "mn"
    if style == "bn":
        text = f"{value / 1000:.2f}".rstrip("0").rstrip(".")
        return f"EUR {text} billion"
    if style == "int":
        return f"EUR {value:,.0f} million"
    if style == "m":
        return f"EUR {value:,.1f}m"
    return f"EUR {value:,.1f} million"


def fmt_pct(value: float, rng: Random | None = None) -> str:
    return f"{value:.1f}%" if rng and rng.random() < 0.3 else f"{value:.1f} percent"


def fmt_count(value: float) -> str:
    return f"{int(round(value)):,}"


def fmt_value(vkind: str, value: float, rng: Random | None = None, style: str | None = None) -> str:
    if vkind == "money":
        return fmt_money(value, rng, style)
    if vkind == "pct":
        return fmt_pct(value, rng)
    if vkind == "count":
        return fmt_count(value)
    if vkind == "year":
        return str(int(value))
    if vkind == "months":
        return f"{int(value)} months"
    if vkind == "weeks":
        return f"{int(value)} weeks"
    if vkind == "multiple":
        return f"{value:.1f}x"
    raise ValueError(vkind)


def period_long(period: str, rng: Random | None = None) -> str:
    year = period.removeprefix("FY")
    if rng is not None and rng.random() < 0.4:
        return f"fiscal {year}"
    return f"the year ended 31 December {year}"


# ---- metrics ------------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str  # canonical word(s) a claim would use
    unit: str
    vkind: str  # money | pct | count | year | months | weeks | multiple
    lit: tuple[str, ...]
    par: tuple[str, ...]
    row: str
    foot: str
    claim: str
    questions: tuple[str, ...]
    par_questions: tuple[str, ...]
    static: bool = False
    synonyms: tuple[str, ...] = field(default_factory=tuple)

    def keywords(self, period: str) -> list[str]:
        return [self.label] if self.static else [self.label, period]


def _m(**kw: object) -> MetricDef:
    return MetricDef(**kw)  # type: ignore[arg-type]


METRICS: dict[str, MetricDef] = {
    m.key: m
    for m in [
        _m(
            key="revenue", label="revenue", unit="EUR m", vkind="money",
            lit=(
                "Net revenue for {P} reached {V} ({PP}: {VP}).",
                "{E} generated revenue of {V} in {P}.",
                "Revenue amounted to {V} in {P}.",
            ),
            par=(
                "Turnover climbed to {V} over {PL}.",
                "Sales totalled {V} for {PL}.",
                "The top line came in at {V} in {PL}.",
            ),
            row="Revenue", foot="Revenue for {P} is stated net of rebates and discounts: {V}.",
            claim="{E} revenue for {P} was {V}.",
            questions=("What was {E}'s revenue in {P}?", "How much revenue did {E} report for {P}?"),
            par_questions=("How large was {E}'s turnover in {PL}?", "What were {E}'s total sales for {PL}?"),
            synonyms=("turnover", "sales"),
        ),
        _m(
            key="ebitda", label="EBITDA", unit="EUR m", vkind="money",
            lit=(
                "EBITDA for {P} was {V} ({PP}: {VP}).",
                "{E} reported EBITDA of {V} in {P}.",
                "EBITDA reached {V} in {P}.",
            ),
            par=(
                "Earnings before interest, tax, depreciation and amortisation stood at {V} for {PL}.",
                "{E} earned {V} before interest, tax, depreciation and amortisation in {PL}.",
                "Operating earnings before depreciation and amortisation were {V} in {PL}.",
            ),
            row="EBITDA", foot="EBITDA for {P} is stated before non-recurring items: {V}.",
            claim="{E} EBITDA for {P} was {V}.",
            questions=("What was {E}'s EBITDA in {P}?", "How much EBITDA did {E} report for {P}?"),
            par_questions=("What were {E}'s earnings before interest, tax, depreciation and amortisation in {PL}?",),
        ),
        _m(
            key="adjusted_ebitda", label="adjusted EBITDA", unit="EUR m", vkind="money",
            lit=(
                "Adjusted EBITDA for {P} was {V} after normalisation adjustments.",
                "{E} adjusted EBITDA for {P} amounted to {V}.",
            ),
            par=("After normalisation adjustments, underlying operating earnings were {V} in {PL}.",),
            row="Adjusted EBITDA", foot="Adjusted EBITDA for {P}: {V}.",
            claim="{E} adjusted EBITDA for {P} was {V}.",
            questions=("What was {E}'s adjusted EBITDA in {P}?",),
            par_questions=("What were {E}'s underlying operating earnings after adjustments in {PL}?",),
        ),
        _m(
            key="gross_margin", label="gross margin", unit="%", vkind="pct",
            lit=(
                "Gross margin was {V} in {P}.",
                "{E} achieved a gross margin of {V} in {P}.",
                "The gross margin for {P} stood at {V}.",
            ),
            par=(
                "After direct production costs, {V} of sales remained as profit in {PL}.",
                "Profit after cost of goods sold represented {V} of sales in {PL}.",
            ),
            row="Gross margin", foot="Gross margin for {P} excludes depreciation: {V}.",
            claim="{E} gross margin for {P} was {V}.",
            questions=("What was {E}'s gross margin in {P}?", "How high was the gross margin of {E} in {P}?"),
            par_questions=("What share of sales did {E} keep after direct production costs in {PL}?",),
        ),
        _m(
            key="ebitda_margin", label="EBITDA margin", unit="%", vkind="pct",
            lit=(
                "EBITDA margin was {V} in {P}.",
                "{E} delivered an EBITDA margin of {V} in {P}.",
            ),
            par=("Operating earnings before depreciation represented {V} of sales in {PL}.",),
            row="EBITDA margin", foot="EBITDA margin for {P}: {V}.",
            claim="{E} EBITDA margin for {P} was {V}.",
            questions=("What was {E}'s EBITDA margin in {P}?",),
            par_questions=("What share of sales did {E} earn as operating profit before depreciation in {PL}?",),
        ),
        _m(
            key="top_customer_share", label="largest customer share", unit="%", vkind="pct",
            lit=(
                "The largest customer represented {V} of {P} revenue.",
                "The top customer accounted for {V} of {P} revenue.",
            ),
            par=("A single client contributed {V} of sales in {PL}, the highest share of any buyer.",),
            row="Largest customer share", foot="The largest customer share for {P} is {V}.",
            claim="The largest customer of {E} represented {V} of {P} revenue.",
            questions=(
                "What share of {P} revenue came from the largest customer of {E}?",
                "How concentrated is the customer base of {E} in {P}, measured by the top customer?",
            ),
            par_questions=("How much of {E}'s sales in {PL} depended on its biggest client?",),
        ),
        _m(
            key="top10_customer_share", label="top ten customers share", unit="%", vkind="pct",
            lit=("The ten largest customers represented {V} of {P} revenue.",),
            par=("Together, the leading ten clients accounted for {V} of sales in {PL}.",),
            row="Top ten customers share", foot="The ten largest customers represent {V} of {P} revenue.",
            claim="The ten largest customers of {E} represented {V} of {P} revenue.",
            questions=("What share of {P} revenue came from the ten largest customers of {E}?",),
            par_questions=("How much of {E}'s sales in {PL} came from its leading ten clients?",),
        ),
        _m(
            key="headcount", label="headcount", unit="employees", vkind="count",
            lit=(
                "The company employed {V} people at the end of {P}.",
                "Headcount stood at {V} at year end {P}.",
            ),
            par=("{E} had a workforce of {V} employees at the close of {PL}.",),
            row="Headcount", foot="Headcount at the end of {P}: {V} employees.",
            claim="{E} headcount at the end of {P} was {V}.",
            questions=("How many people did {E} employ at the end of {P}?", "What was the headcount of {E} in {P}?"),
            par_questions=("How large was the workforce of {E} at the close of {PL}?",),
        ),
        _m(
            key="capex", label="capital expenditure", unit="EUR m", vkind="money",
            lit=("Capital expenditure was {V} in {P}.", "{E} invested {V} in capital expenditure in {P}."),
            par=("Investment in property, plant and equipment amounted to {V} in {PL}.",),
            row="Capital expenditure", foot="Capital expenditure for {P}: {V}.",
            claim="{E} capital expenditure in {P} was {V}.",
            questions=("What was {E}'s capital expenditure in {P}?",),
            par_questions=("How much did {E} invest in property, plant and equipment in {PL}?",),
        ),
        _m(
            key="net_debt", label="net debt", unit="EUR m", vkind="money",
            lit=("Net debt at the end of {P} was {V}.", "{E} reported net debt of {V} at the end of {P}."),
            par=("Borrowings less cash stood at {V} at the close of {PL}.",),
            row="Net debt", foot="Net debt at the end of {P}: {V}.",
            claim="{E} net debt at the end of {P} was {V}.",
            questions=("What was {E}'s net debt at the end of {P}?",),
            par_questions=("What were {E}'s borrowings less cash at the close of {PL}?",),
        ),
        _m(
            key="order_backlog", label="order backlog", unit="EUR m", vkind="money",
            lit=("The order backlog stood at {V} at the end of {P}.", "{E} had an order backlog of {V} at the end of {P}."),
            par=("Contracted orders not yet delivered totalled {V} at the close of {PL}.",),
            row="Order backlog", foot="Order backlog at the end of {P}: {V}.",
            claim="{E} order backlog at the end of {P} was {V}.",
            questions=("What was {E}'s order backlog at the end of {P}?",),
            par_questions=("How much contracted but undelivered business did {E} hold at the close of {PL}?",),
        ),
        _m(
            key="plants", label="production sites", unit="count", vkind="count",
            lit=("As of {P}, the company operated {V} production sites.", "{E} runs {V} production sites as of {P}."),
            par=("Manufacturing is spread over {V} plants as of {PL}.",),
            row="Production sites", foot="Number of production sites in {P}: {V}.",
            claim="{E} operated {V} production sites as of {P}.",
            questions=("How many production sites did {E} operate as of {P}?",),
            par_questions=("Over how many plants is {E}'s manufacturing spread as of {PL}?",),
        ),
        _m(
            key="enterprise_value", label="enterprise value", unit="EUR m", vkind="money",
            lit=("The indicative enterprise value is {V}.", "The transaction values the company at an enterprise value of {V}."),
            par=("On a cash-free and debt-free basis the business is priced at {V}.",),
            row="Enterprise value", foot="Enterprise value: {V}.",
            claim="The enterprise value of {E} is {V}.",
            questions=("What is the enterprise value of {E} in the transaction?",),
            par_questions=("At what cash-free and debt-free price is {E} offered?",),
            static=True,
        ),
        _m(
            key="equity_value", label="equity value", unit="EUR m", vkind="money",
            lit=("The indicative equity value is {V}.", "After net debt, the equity value of the company is {V}."),
            par=("Shareholders would receive {V} for their shares after settling net debt.",),
            row="Equity value", foot="Equity value: {V}.",
            claim="The equity value of {E} is {V}.",
            questions=("What is the equity value of {E} in the transaction?",),
            par_questions=("How much would shareholders of {E} receive after net debt is settled?",),
            static=True,
        ),
        _m(
            key="export_share", label="export share", unit="%", vkind="pct",
            lit=("Exports accounted for {V} of sales in {P}.", "{E} generated {V} of its sales abroad in {P}."),
            par=("Foreign customers bought {V} of the output in {PL}.",),
            row="Export share", foot="Export share in {P}: {V}.",
            claim="{E} export share in {P} was {V}.",
            questions=("What share of {E}'s sales were exports in {P}?",),
            par_questions=("How much of {E}'s output went to foreign customers in {PL}?",),
        ),
        _m(
            key="market_share", label="market share", unit="%", vkind="pct",
            lit=("{E} holds a market share of {V} in its core European segment.", "The market share of {E} in Europe was {V} in {P}."),
            par=("{E} controls {V} of European sales in its main segment as of {PL}.",),
            row="Market share", foot="Market share in {P}: {V}.",
            claim="{E} market share in {P} was {V}.",
            questions=("What market share did {E} hold in {P}?",),
            par_questions=("How much of its main European segment did {E} control in {PL}?",),
        ),
        _m(
            key="aum", label="assets under management", unit="EUR m", vkind="money",
            lit=(
                "Assets under management were {V} at the end of {P}.",
                "{E} had assets under management of {V} as of {P}.",
            ),
            par=("The platform administers {V} on behalf of its investors as of {PL}.",),
            row="Assets under management", foot="Assets under management at the end of {P}: {V}.",
            claim="{E} assets under management at the end of {P} were {V}.",
            questions=("What were {E}'s assets under management at the end of {P}?", "How large is {E} by assets under management in {P}?"),
            par_questions=("How much does {E} administer for its investors as of {PL}?",),
        ),
        _m(
            key="market_cap", label="market capitalisation", unit="EUR m", vkind="money",
            lit=(
                "{E} had a market capitalisation of {V} at the end of {P}.",
                "Market capitalisation was {V} at the end of {P}.",
            ),
            par=("The equity of {E} was valued at {V} on the exchange at the close of {PL}.",),
            row="Market capitalisation", foot="Market capitalisation at the end of {P}: {V}.",
            claim="{E} market capitalisation at the end of {P} was {V}.",
            questions=("What was {E}'s market capitalisation at the end of {P}?",),
            par_questions=("How was the equity of {E} valued on the exchange at the close of {PL}?",),
        ),
        _m(
            key="fund_vintage_year", label="fund vintage year", unit="year", vkind="year",
            lit=("The fund was launched in {V}.", "{E} closed its current fund with a vintage year of {V}."),
            par=("The vehicle began its life as an investor pool in {V}.",),
            row="Fund vintage year", foot="Fund vintage year: {V}.",
            claim="The current fund of {E} has a vintage year of {V}.",
            questions=("What is the vintage year of the current fund of {E}?",),
            par_questions=("When did the current investment vehicle of {E} begin?",),
            static=True,
        ),
        _m(
            key="investment_period_end_year", label="investment period end", unit="year", vkind="year",
            lit=("The investment period of the fund ends in {V}.", "{E} can make new platform investments until {V}, when the investment period ends."),
            par=("New platform deals may be signed by the fund until {V}.",),
            row="Investment period end", foot="Investment period end: {V}.",
            claim="The investment period of the fund of {E} ends in {V}.",
            questions=("When does the investment period of the fund of {E} end?",),
            par_questions=("Until when may the fund of {E} sign new platform deals?",),
            static=True,
        ),
        _m(
            key="portfolio_companies", label="portfolio companies", unit="count", vkind="count",
            lit=("The fund holds {V} portfolio companies as of {P}.", "{E} owned {V} portfolio companies as of {P}."),
            par=("{E} backs {V} operating businesses as of {PL}.",),
            row="Portfolio companies", foot="Portfolio companies in {P}: {V}.",
            claim="{E} had {V} portfolio companies as of {P}.",
            questions=("How many portfolio companies did {E} hold as of {P}?",),
            par_questions=("How many operating businesses did {E} back as of {PL}?",),
        ),
        _m(
            key="ticket_min", label="minimum ticket", unit="EUR m", vkind="money",
            lit=("The fund targets equity tickets of {V} to {V2} per transaction.",),
            par=("Each deal receives an equity cheque between {V} and {V2}.",),
            row="Minimum ticket", foot="Minimum equity ticket: {V}.",
            claim="The minimum equity ticket of {E} is {V}.",
            questions=("What is the minimum equity ticket of {E}?",),
            par_questions=("What is the smallest equity cheque {E} writes?",),
            static=True,
        ),
        _m(
            key="ticket_max", label="maximum ticket", unit="EUR m", vkind="money",
            lit=("The fund targets equity tickets of {V1} to {V} per transaction.",),
            par=("Each deal receives an equity cheque between {V1} and {V}.",),
            row="Maximum ticket", foot="Maximum equity ticket: {V}.",
            claim="The maximum equity ticket of {E} is {V}.",
            questions=("What is the maximum equity ticket of {E}?",),
            par_questions=("What is the largest equity cheque {E} writes?",),
            static=True,
        ),
        # general knowledge layer
        _m(
            key="process_weeks", label="process duration", unit="weeks", vkind="weeks",
            lit=("{E} runs for about {V} from teaser to signing.", "A typical {E} lasts {V}."),
            par=("From first teaser to signature, {E} takes around {V}.",),
            row="Process duration", foot="Process duration: {V}.",
            claim="{E} lasts {V}.",
            questions=("How long does {E} usually last?",),
            par_questions=("How many weeks pass between teaser and signature in {E}?",),
            static=True,
        ),
        _m(
            key="nda_term_months", label="confidentiality term", unit="months", vkind="months",
            lit=("The standard confidentiality term in {E} is {V}.", "{E} sets the confidentiality term at {V}."),
            par=("Under {E}, secrecy obligations last {V}.",),
            row="Confidentiality term", foot="Confidentiality term: {V}.",
            claim="The confidentiality term in {E} is {V}.",
            questions=("What is the standard confidentiality term in {E}?",),
            par_questions=("How long do secrecy obligations last under {E}?",),
            static=True,
        ),
        _m(
            key="bidder_rounds", label="bidding rounds", unit="count", vkind="count",
            lit=("{E} foresees {V} bidding rounds.", "The auction in {E} has {V} bidding rounds."),
            par=("Bidders go through {V} stages of offers in {E}.",),
            row="Bidding rounds", foot="Bidding rounds: {V}.",
            claim="{E} has {V} bidding rounds.",
            questions=("How many bidding rounds does {E} foresee?",),
            par_questions=("Through how many stages of offers do bidders go in {E}?",),
            static=True,
        ),
        _m(
            key="break_fee_pct", label="break fee", unit="%", vkind="pct",
            lit=("The usual break fee in {E} is {V} of the equity value.", "{E} proposes a break fee of {V} of the equity value."),
            par=("A seller walking away pays {V} of the equity value under {E}.",),
            row="Break fee", foot="Break fee: {V} of equity value.",
            claim="The break fee in {E} is {V} of the equity value.",
            questions=("What break fee does {E} propose?",),
            par_questions=("What does a seller walking away pay under {E}?",),
            static=True,
        ),
        _m(
            key="precedent_multiple", label="EV to EBITDA multiple", unit="x", vkind="multiple",
            lit=("{E} was priced at an EV to EBITDA multiple of {V}.", "The EV to EBITDA multiple paid in {E} was {V}."),
            par=("Buyers paid {V} of operating earnings before depreciation for {E}.",),
            row="EV to EBITDA multiple", foot="EV to EBITDA multiple: {V}.",
            claim="The EV to EBITDA multiple of {E} was {V}.",
            questions=("What EV to EBITDA multiple was paid in {E}?",),
            par_questions=("How many times operating earnings before depreciation did buyers pay for {E}?",),
            static=True,
        ),
    ]
}


def metric(key: str) -> MetricDef:
    return METRICS[key]


# ---- sentence rendering -------------------------------------------------------------------


def render_sentence(
    m: MetricDef,
    *,
    entity: str,
    period: str,
    value: float,
    form: str,
    rng: Random,
    prev: tuple[str, float] | None = None,
    with_entity: bool = True,
    force: int | None = None,
    extra: float | None = None,
    value_style: str | None = None,
) -> tuple[str, bool]:
    """One sentence stating the fact. Returns (text, used_prev). `extra` is the second value
    of range templates (ticket min and max share one sentence)."""
    pool = m.lit if form == "lit" else m.par
    if force is not None:
        template = pool[force]
    else:
        usable = [
            t
            for t in pool
            if (with_entity or "{E}" not in t) and (prev is not None or "{PP}" not in t)
        ]
        template = usable[rng.randrange(len(usable))] if usable else pool[0]
    fields: dict[str, str] = {
        "E": entity,
        "P": period,
        "PL": period_long(period, rng),
        "V": fmt_value(m.vkind, value, rng, value_style),
    }
    if prev is not None:
        fields["PP"] = prev[0]
        fields["VP"] = fmt_value(m.vkind, prev[1], rng, value_style or "mn")
    if extra is not None:
        fields["V2"] = fmt_value(m.vkind, extra, rng, "mn")
        fields["V1"] = fmt_value(m.vkind, extra, rng, "mn")
    used_prev = "{PP}" in template
    return template.format(**fields), used_prev


def claim_text(m: MetricDef, entity: str, period: str, value: float) -> str:
    return m.claim.format(E=entity, P=period, V=fmt_value(m.vkind, value, None, "mn"))


def question_text(m: MetricDef, entity: str, period: str, rng: Random, paraphrased: bool) -> str:
    pool = m.par_questions if paraphrased else m.questions
    return pool[rng.randrange(len(pool))].format(E=entity, P=period, PL=period_long(period))


# ---- names --------------------------------------------------------------------------------

_SYL_A = ["val", "dor", "kes", "tra", "nov", "mer", "sen", "bri", "lan", "car", "est", "fyn",
          "gor", "hal", "ith", "jun", "kor", "lum", "nar", "ost", "pel", "quin", "rav", "sol",
          "tarn", "ul", "vex", "wyn", "yor", "zan", "bel", "cor", "dra", "eln", "fal", "gwen"]
_SYL_B = ["ix", "ane", "ora", "ium", "ex", "ova", "ent", "is", "ar", "on", "ik", "ell", "und",
          "ay", "eth", "ord", "ani", "uro", "ald", "ing"]
FIRST_NAMES = ["Anna", "Marc", "Lena", "Jonas", "Sofia", "Felix", "Clara", "Tomas", "Ingrid",
               "Pavel", "Marta", "Henrik", "Nora", "Viktor", "Elena", "Lukas", "Greta", "Daniel",
               "Petra", "Oskar", "Mira", "Stefan", "Irene", "Karl", "Laura", "Emil", "Hanna",
               "Rolf", "Alma", "Niklas"]
CITIES = ["Rovenburg", "Alderfeld", "Kastrow", "Mirlund", "Tavenhof", "Eskelby", "Dornach Ost",
          "Halvmark", "Brennau", "Sulmark", "Orvelt", "Wendholm", "Falkerath", "Ostrava Nord",
          "Linnefeld", "Garvik"]


class NamePool:
    """Unique fictional names. Never reuses a name, so no entity is confused with another."""

    def __init__(self, rng: Random) -> None:
        self._rng = rng
        self._used: set[str] = set()

    def stem(self) -> str:
        while True:
            name = (
                self._rng.choice(_SYL_A).capitalize()
                + self._rng.choice(_SYL_B)
            )
            if name not in self._used:
                self._used.add(name)
                return name

    def person(self) -> str:
        return f"{self._rng.choice(FIRST_NAMES)} {self.stem()}"

    def reserve(self, name: str) -> None:
        self._used.add(name)
