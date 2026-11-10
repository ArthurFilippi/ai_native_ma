"""Rules behind the offline writer and the offline judge (the `mock` provider).

They are pure functions of text, so the same inputs always give the same claims and labels.

Writer: for each sub-question the asked metrics, periods and entity are read, every passage is
searched for a fact `(metric, period, value)` (sentences and table cells), and each fact becomes
one claim written in a canonical form (`Aurora Components revenue for FY2024 was EUR 182.4
million.`) with the sentence or table row it came from as the verbatim quote. A paraphrase such as
`Turnover climbed to EUR 182.4 million over fiscal 2024` is therefore stated in the words of the
question and still quoted exactly.

Judge: the facts of the claim are compared with the facts of the quote (and of the table rows the
quote contains, whose header lives in the surrounding chunk): all verified is `supported`, some is
`partial`, none is `unsupported`; a verified fact about another company is `unsupported`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from ainma.pipeline.schemas import NumberedPassage
from ainma.retrieval.entities import entity_phrases, names_other_entity
from ainma.retrieval.lexicon import METRIC_BY_KEY, detect_periods, target_metrics
from ainma.retrieval.quantities import STATIC_PERIOD, ExtractedFact, extract_facts_rules

# ---- claims ------------------------------------------------------------------------------------


def format_value(fact: ExtractedFact) -> str:
    """The value as a claim states it: money in millions, percent, counts, years, multiples."""
    value = fact.value
    if fact.unit.endswith(" m"):
        return f"{fact.unit[:-2]} {value:,.1f} million"
    if fact.unit == "%":
        return f"{value:.1f} percent"
    if fact.unit == "x":
        return f"{value:.1f}x"
    if fact.unit == "year":
        return str(int(value))
    text = f"{int(round(value)):,}" if math.isclose(value, round(value)) else f"{value:,.1f}"
    after = fact.sentence[fact.end - fact.sentence_start :].lstrip()
    unit_word = re.match(r"(weeks?|months?)\b", after, re.IGNORECASE)
    return f"{text} {unit_word.group(1).lower()}" if unit_word else text


def claim_text(subject: str, fact: ExtractedFact, period: str | None) -> str:
    label = METRIC_BY_KEY[fact.metric].label
    head = f"{subject} {label}".strip() if subject else label.capitalize()
    value = format_value(fact)
    if METRIC_BY_KEY[fact.metric].static or period is None:
        return f"{head} is {value}."
    return f"{head} for {period} was {value}."


@dataclass(frozen=True)
class Selection:
    passage: NumberedPassage
    fact: ExtractedFact
    metric: str
    period: str | None  # the period asked for, or the fact's own when none was asked


def effective_period(fact: ExtractedFact, passage: NumberedPassage) -> str | None:
    """The period a fact speaks about. A figure without a period (`X is reported to manage roughly
    EUR 680 million`) describes the latest fiscal year before its source was published, as press
    does: an article of February 2025 speaks about FY2024. None when the source has no date."""
    if fact.period is not None:
        return fact.period
    published = passage.published_on
    if published is None:
        return None
    return f"FY{published.year - 1 if published.month <= 9 else published.year}"


def select_facts(
    sub_question: str, passages: Sequence[NumberedPassage], *, limit: int, entity: Sequence[str]
) -> list[Selection] | None:
    """Facts that answer `sub_question`, best passage first, at most `limit` per metric and
    period. None when the question names no metric (the caller falls back to word overlap).

    Without a period in the question the latest period any source states is answered, so an old
    deck does not add a stale figure next to the current one."""
    metrics = target_metrics(sub_question)
    if not metrics:
        return None
    asked: list[str | None] = list(detect_periods(sub_question)) or [None]
    parsed = [(p, extract_facts_rules(p.text)) for p in passages]
    chosen: list[Selection] = []
    seen: set[tuple[int, str, str, float]] = set()
    for metric in metrics:
        candidates = [
            (
                passage,
                fact,
                STATIC_PERIOD if fact.period == STATIC_PERIOD else effective_period(fact, passage),
            )
            for passage, facts in parsed
            for fact in facts
            if fact.metric == metric and not (entity and names_other_entity(fact.sentence, entity))
        ]
        dated = [period for _, _, period in candidates if period not in (None, STATIC_PERIOD)]
        for wanted in asked:
            target = wanted or (max(dated) if dated else None)
            taken = 0
            for passage, _ in parsed:
                if taken >= limit:
                    break
                fits = [
                    (fact, period)
                    for p, fact, period in candidates
                    if p is passage
                    and (period in (STATIC_PERIOD, None) or target is None or period == target)
                ]
                if not fits:
                    continue
                fact, period = fits[0]
                claimed = target if period != STATIC_PERIOD else None
                key = (passage.n, metric, claimed or "", fact.value)
                if key in seen:
                    continue
                seen.add(key)
                chosen.append(Selection(passage, fact, metric, claimed))
                taken += 1
    return chosen


def subject_of(question: str) -> str:
    """The company the question is about: its longest capitalised phrase (`Ostis Industries`
    rather than `European`)."""
    phrases = entity_phrases(question)
    return max(phrases, key=lambda p: len(p.split())) if phrases else ""


# ---- judge -------------------------------------------------------------------------------------


def _same_value(a: ExtractedFact, b: ExtractedFact) -> bool:
    return a.unit == b.unit and math.isclose(a.value, b.value, rel_tol=1e-6, abs_tol=1e-9)


def _same_period(claim: ExtractedFact, evidence: ExtractedFact) -> bool:
    if STATIC_PERIOD in (claim.period, evidence.period):
        return claim.period == evidence.period or claim.period is None or evidence.period is None
    return claim.period is None or evidence.period is None or claim.period == evidence.period


def evidence_facts(quote: str, context: str) -> list[ExtractedFact]:
    """Facts stated by the quote, plus the cells of the table rows the quote contains: a row such
    as `Revenue | 140.1 | 152.6` takes its periods from the header of the surrounding chunk."""
    facts = extract_facts_rules(quote)
    if context and context != quote:
        rows = [f for f in extract_facts_rules(context) if f.from_table]
        facts.extend(f for f in rows if f.sentence.strip() and f.sentence.strip() in quote)
    return facts


def verified_share(claim_facts: Sequence[ExtractedFact], evidence: Sequence[ExtractedFact]) -> int:
    """How many facts of the claim some fact of the evidence states (metric, value, period)."""
    return sum(
        any(e.metric == c.metric and _same_value(c, e) and _same_period(c, e) for e in evidence)
        for c in claim_facts
    )
