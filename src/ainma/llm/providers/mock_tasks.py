"""Deterministic offline routines for every LLM task (the `mock` provider).

- understand: rule based decomposition (`ainma.pipeline.understand.understand_rules`);
- write: extractive. For each sub-question it keeps, passage by passage, the sentence that states
  the asked metric as a number for the asked period (or, without a metric, the sentence covering
  most query terms) and returns it verbatim as claim and quote. A question about growth adds an
  INFERRED claim computed from two quoted figures;
- judge: labels a (claim, quotes) pair from number overlap, metric and period binding, proper
  noun overlap and word coverage; the same task also rates answer relevance (term coverage);
- extract_facts: the rule based extractor of `ainma.retrieval.quantities`.

`kpi_parse` is deliberately not registered: KPI parsing in mock mode is a regex routine inside
`ainma.kpi` (owned by `biz`, DECISIONS D05), so asking the mock for it fails loudly.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from ainma.llm.mock import MockHandler
from ainma.llm.tasks import TASK_EXTRACT_FACTS, TASK_JUDGE, TASK_UNDERSTAND, TASK_WRITE
from ainma.pipeline.schemas import (
    DraftClaim,
    DraftEvidence,
    ExtractFactsRequest,
    ExtractFactsResult,
    FactItem,
    JudgeRequest,
    JudgeResult,
    NumberedPassage,
    RelevanceRequest,
    RelevanceResult,
    UnderstandRequest,
    WriteRequest,
    WriteResult,
)
from ainma.pipeline.understand import _GROWTH, understand_rules
from ainma.pipeline.verify import numeric_match
from ainma.retrieval.lexicon import METRIC_BY_KEY, METRICS, detect_periods, previous_period
from ainma.retrieval.quantities import (
    ExtractedFact,
    extract_facts_rules,
    parse_quantities,
    quantities_match,
)
from ainma.retrieval.text import STOPWORDS, sentence_spans, tokenize

# ---- understand ---------------------------------------------------------------------------------


def _understand(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    request = UnderstandRequest.model_validate_json(user)
    return understand_rules(request.question)


# ---- write --------------------------------------------------------------------------------------

_COVERAGE_MIN = 0.6


def _period_ok(wanted: list[str], sentence_periods: set[str], passage_periods: set[str]) -> bool:
    if not wanted:
        return True
    if sentence_periods:
        return bool(sentence_periods & set(wanted))
    return set(wanted) <= passage_periods


def _select_sentences(
    sub_question: str, passages: list[NumberedPassage], limit: int
) -> list[tuple[NumberedPassage, str]]:
    from ainma.retrieval.lexicon import detect_metrics

    metrics, periods = detect_metrics(sub_question), detect_periods(sub_question)
    terms = set(tokenize(sub_question))
    picked: list[tuple[NumberedPassage, str]] = []
    for passage in passages:
        passage_periods = set(detect_periods(passage.text))
        best: tuple[float, str] | None = None
        for start, end in sentence_spans(passage.text):
            sentence = passage.text[start:end]
            sentence_periods = set(detect_periods(sentence))
            if not _period_ok(periods, sentence_periods, passage_periods):
                continue
            if metrics:
                facts = extract_facts_rules(sentence)
                if any(f.metric in metrics for f in facts):
                    best = (1.0, sentence)
                    break
                continue
            overlap = terms & set(tokenize(sentence))
            needed = 1 if len(terms) < 2 else 2
            coverage = len(overlap) / len(terms) if terms else 0.0
            if (
                len(overlap) >= needed
                and coverage >= _COVERAGE_MIN
                and (best is None or coverage > best[0])
            ):
                best = (coverage, sentence)
        if best is not None:
            picked.append((passage, best[1]))
        if len(picked) >= limit:
            break
    return picked


def _growth_claim(
    claims: list[DraftClaim], facts_by_claim: dict[str, list[ExtractedFact]], next_id: int
) -> DraftClaim | None:
    entries = [(cid, f) for cid, fs in facts_by_claim.items() for f in fs if f.period]
    for metric in dict.fromkeys(f.metric for _, f in entries):
        by_period: dict[str, tuple[str, ExtractedFact]] = {}
        for cid, fact in entries:
            if fact.metric == metric and fact.period:
                by_period.setdefault(fact.period, (cid, fact))
        for period in sorted(by_period, reverse=True):
            prior = previous_period(period)
            if (
                prior
                and prior in by_period
                and by_period[prior][1].unit == by_period[period][1].unit
            ):
                (c1, new), (c0, old) = by_period[period], by_period[prior]
                if old.value == 0:
                    continue
                change = (new.value / old.value - 1.0) * 100.0
                verb = "grew" if change >= 0 else "fell"
                label = METRIC_BY_KEY[metric].label
                text = (
                    f"Using the quoted figures, {label} {verb} about {abs(change):.1f}% from "
                    f"{prior} to {period} ({new.value:g} / {old.value:g} - 1)."
                )
                derived = list(dict.fromkeys([c1, c0]))
                return DraftClaim(
                    id=f"d{next_id}", text=text, status="inferred", derived_from=derived
                )
    return None


def _write(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    request = WriteRequest.model_validate_json(user)
    claims: list[DraftClaim] = []
    by_key: dict[tuple[int, str], str] = {}
    missing: list[str] = []
    for sub_question in request.sub_questions or [request.question]:
        picked = _select_sentences(sub_question, request.passages, request.max_claims)
        if not picked:
            missing.append(sub_question)
        for passage, sentence in picked:
            key = (passage.n, sentence)
            if key in by_key:
                continue
            claim = DraftClaim(
                id=f"d{len(claims) + 1}",
                text=sentence,
                status="sourced",
                evidence=[DraftEvidence(passage=passage.n, quote=sentence)],
            )
            by_key[key] = claim.id
            claims.append(claim)
    if _GROWTH.search(request.question):
        facts = {c.id: extract_facts_rules(c.text) for c in claims}
        inferred = _growth_claim(claims, facts, len(claims) + 1)
        if inferred is not None:
            claims.append(inferred)
    return WriteResult(claims=claims, missing=missing)


# ---- judge --------------------------------------------------------------------------------------

_GENERIC = frozenset(
    [
        "state",
        "report",
        "according",
        "show",
        "reach",
        "approximately",
        "roughly",
        "cim",
        "document",
        "source",
        "quote",
        "record",
        "use",
        "using",
        "figure",
    ]
)
_PROPER = re.compile(r"\b[A-Z][a-z]{2,}\b")
_COMMON = (
    frozenset(word for metric in METRICS for phrase in metric.phrases for word in phrase.split())
    | STOPWORDS
    | frozenset(
        [
            "january",
            "february",
            "march",
            "april",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
            "using",
            "sources",
            "source",
            "trade",
            "press",
            "total",
            "company",
            "group",
            "management",
            "customers",
            "adjusted",
            "reported",
        ]  # fmt: skip
    )
)


def _facts_agree(a: ExtractedFact, b: ExtractedFact) -> bool:
    period_ok = a.period is None or b.period is None or a.period == b.period
    close = abs(a.value - b.value) <= 1e-9 * max(1.0, abs(a.value), abs(b.value))
    return period_ok and a.unit == b.unit and close


def judge_support(claim: str, quotes: list[str], context: str = "") -> JudgeResult:
    quote = " ".join(quotes)
    claim_numbers = [q for q in parse_quantities(claim) if q.kind != "year"]
    quote_numbers = parse_quantities(quote)
    if claim_numbers:
        matched = sum(any(quantities_match(c, q) for q in quote_numbers) for c in claim_numbers)
        if matched == 0:
            _, detail = numeric_match(claim, quote)
            return JudgeResult(label="unsupported", rationale=detail)
        if matched < len(claim_numbers):
            return JudgeResult(label="partial", rationale="only some numbers are in the quote")
    quote_years = [q for q in quote_numbers if q.kind == "year"]
    for year in (q for q in parse_quantities(claim) if q.kind == "year"):
        if not any(quantities_match(year, other) for other in quote_years):
            label = "unsupported" if quote_years else "partial"
            return JudgeResult(label=label, rationale=f"{year.text} is not stated by the quote")
    quote_facts = extract_facts_rules(quote)
    mismatched = 0
    checked = 0
    for fact in extract_facts_rules(claim):
        same_metric = [q for q in quote_facts if q.metric == fact.metric]
        if same_metric:
            checked += 1
            mismatched += not any(_facts_agree(fact, q) for q in same_metric)
    if mismatched:
        label = "unsupported" if mismatched == checked else "partial"
        return JudgeResult(label=label, rationale="metric, period and value do not line up")
    known = set(tokenize(f"{quote} {context}"))
    missing_entities = [
        w
        for w in _PROPER.findall(claim)
        if w.lower() not in _COMMON and tokenize(w)[0] not in known
    ]
    if missing_entities:
        return JudgeResult(
            label="unsupported", rationale=f"not named in the sources: {missing_entities[0]}"
        )
    terms = {t for t in tokenize(claim) if not t[0].isdigit() and t not in _GENERIC}
    if not terms:
        return JudgeResult(label="supported", rationale="nothing but figures, all matched")
    coverage = len(terms & set(tokenize(quote))) / len(terms)
    if coverage >= 0.6:
        return JudgeResult(label="supported", rationale=f"word coverage {coverage:.2f}")
    if coverage >= 0.35:
        return JudgeResult(label="partial", rationale=f"word coverage {coverage:.2f}")
    return JudgeResult(label="unsupported", rationale=f"word coverage {coverage:.2f}")


def judge_relevance(question: str, answer: str) -> RelevanceResult:
    terms = {t for t in tokenize(question) if t not in _GENERIC}
    if not terms:
        return RelevanceResult(score=0.0, rationale="no content term in the question")
    covered = len(terms & set(tokenize(answer))) / len(terms)
    return RelevanceResult(score=covered, rationale=f"term coverage {covered:.2f}")


def _judge(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    if schema is RelevanceResult:
        relevance_request = RelevanceRequest.model_validate_json(user)
        return judge_relevance(relevance_request.question, relevance_request.answer)
    request = JudgeRequest.model_validate_json(user)
    return judge_support(request.claim, request.quotes, request.context)


# ---- extract facts ------------------------------------------------------------------------------


def _extract_facts(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    request = ExtractFactsRequest.model_validate_json(user)
    return ExtractFactsResult(
        facts=[
            FactItem(metric=f.metric, period=f.period, value=f.value, unit=f.unit, label=f.label)
            for f in extract_facts_rules(request.text)
        ]
    )


def default_mock_handlers() -> dict[str, MockHandler]:
    return {
        TASK_UNDERSTAND: _understand,
        TASK_WRITE: _write,
        TASK_JUDGE: _judge,
        TASK_EXTRACT_FACTS: _extract_facts,
    }
