"""Named entities of a question: the capitalised phrases that are neither question words, nor
metrics, nor periods, nor months.

`What was Aurora Components's gross margin in FY2024?` names `Aurora Components`. The reranker
uses the entity to prefer passages that are about it; the pipeline uses it to say what a claim is
about. Matching is on stemmed tokens (the tokeniser of `ainma.retrieval.text`), so possessives and
plurals do not matter.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection

from ainma.retrieval.lexicon import find_metrics, find_periods
from ainma.retrieval.text import stem, tokenize

QUESTION_WORDS = frozenset(
    [
        "what",
        "who",
        "which",
        "when",
        "where",
        "why",
        "how",
        "is",
        "are",
        "was",
        "were",
        "does",
        "did",
        "do",
        "has",
        "have",
        "can",
        "could",
        "tell",
        "give",
        "list",
        "show",
        "compare",
        "please",
        "in",
        "on",
        "at",
        "for",
        "the",
        "a",
        "an",
        "of",
        "by",
        "with",
        "under",
        "from",
        "through",
        "over",
        "until",
        "between",
        "after",
        "each",
        "new",
    ]
)
MONTHS = frozenset(
    [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ]
)
NON_ENTITY_WORDS = frozenset(
    [
        "europe",
        "european",
        "eu",
        "asia",
        "asian",
        "america",
        "american",
        "africa",
        "african",
        "germany",
        "german",
        "france",
        "french",
        "italy",
        "spain",
        "uk",
        "us",
        "usa",
        "china",
        "chinese",
        "india",
        "nordic",
        "nordics",
        "dach",
        "emea",
        "apac",
        "ebitda",
        "ebit",
        "fy",
        "ev",
    ]
)
"""Capitalised words that are places or finance terms, not the name of a company."""
CURRENCY_CODES = frozenset(["eur", "usd", "gbp", "chf", "sek", "nok", "dkk", "jpy"])
_WORD = re.compile(r"[A-Z][A-Za-z0-9&-]*(?:['’]s)?")
_PERIOD_WORD = re.compile(r"^(?:FY|H[12]|Q[1-4])\d*$", re.IGNORECASE)


def entity_phrases(question: str) -> list[str]:
    """Capitalised phrases of `question` in order of appearance, without repeats."""
    covered = [(a, b) for _, a, b in find_metrics(question)] + [
        (a, b) for _, a, b in find_periods(question)
    ]
    found: dict[str, None] = {}
    words: list[str] = []

    def flush() -> None:
        if words:
            found.setdefault(" ".join(words))
            words.clear()

    previous_end = -1
    for match in _WORD.finditer(question):
        start, end = match.span()
        word = re.sub(r"['’]s$", "", match.group(0))
        lowered = word.lower()
        inside_known = any(a <= start and end <= b for a, b in covered)
        sentence_start = not question[:start].strip()
        skip = (
            inside_known
            or lowered in MONTHS
            or lowered in CURRENCY_CODES
            or _PERIOD_WORD.match(word) is not None
            or (sentence_start and lowered in QUESTION_WORDS)
            or lowered in QUESTION_WORDS
        )
        if skip:
            flush()
        else:
            # consecutive words only when separated by a single space
            if words and question[previous_end:start] != " ":
                flush()
            words.append(word)
            previous_end = end
            if match.group(0) != word:  # a possessive ends the phrase
                flush()
    flush()
    return list(found)


def entity_tokens(question: str) -> list[str]:
    """Distinct stemmed brand tokens of the entities `question` names (`Aurora Components` gives
    `aurora`: the descriptor `components` does not tell companies apart)."""
    tokens: dict[str, None] = {}
    for phrase in entity_phrases(question):
        for token in distinctive_tokens(tokenize(phrase)):
            tokens.setdefault(token)
    return list(tokens)


def entity_overlap(
    wanted: Collection[str], passage_terms: Collection[str], idf: Callable[[str], float] | None
) -> float | None:
    """idf weighted share of the entity tokens `wanted` that the passage contains, None when the
    question names no entity. Rare tokens (`aurora`) weigh more than generic ones
    (`components`)."""
    if not wanted:
        return None
    weight = idf or (lambda _token: 1.0)
    total = sum(weight(t) for t in wanted)
    if total <= 0.0:
        return None
    return sum(weight(t) for t in wanted if t in passage_terms) / total


# ---- the entity a sentence is about ------------------------------------------------------------

GENERIC_NAME_WORDS = frozenset(
    [
        "group",
        "holding",
        "holdings",
        "industries",
        "industry",
        "systems",
        "system",
        "partners",
        "partner",
        "capital",
        "fund",
        "funds",
        "investments",
        "investment",
        "equity",
        "growth",
        "ventures",
        "analytics",
        "components",
        "component",
        "logistics",
        "foods",
        "food",
        "packaging",
        "medical",
        "automotive",
        "containers",
        "water",
        "software",
        "technologies",
        "services",
        "company",
        "corporation",
        "limited",
        "ltd",
        "plc",
        "inc",
        "gmbh",
        "project",
        "the",
    ]
)
"""Descriptors that follow the brand in a company name: `Aurora` is what distinguishes
`Aurora Components`. They are needed to tell a different company (`Aurore Components`) from the
same company named in full or in short."""

_DESCRIPTOR_TOKENS = frozenset(tokenize(" ".join(GENERIC_NAME_WORDS - {"project", "the"}))) | (
    GENERIC_NAME_WORDS - {"project", "the"}
)
# the descriptors as the tokeniser writes them (`analytics` becomes `analytic`)
_GENERIC_TOKENS = _DESCRIPTOR_TOKENS | frozenset(stem(w) for w in GENERIC_NAME_WORDS) | {"project"}


def looks_like_company(phrase: str) -> bool:
    """`Tarnar Industries`, `Merium Water Systems`, `Goron Capital Partners`: a brand followed by
    a corporate descriptor. A heading such as `Cash Flow` or `Income Statement` is not one."""
    words = phrase.split()
    if len(words) < 2 or all(w.isupper() for w in words):
        return False
    last = tokenize(words[-1])
    return bool(last) and last[0] in _DESCRIPTOR_TOKENS


def distinctive_tokens(tokens: Collection[str]) -> list[str]:
    """The tokens that name a company (the brand), or all of them when every one is generic."""
    kept = [t for t in tokens if t not in _GENERIC_TOKENS]
    return kept or list(tokens)


def _edit_distance_at_most_one(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    short, long = sorted((a, b), key=len)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def names_other_entity(sentence: str, wanted: Collection[str]) -> bool:
    """The sentence is about a company other than the one asked about.

    `wanted` are the brand tokens of the asked entity. A sentence that holds all of them is about
    it. Otherwise it names another entity when a capitalised word is a near miss of a wanted
    brand (`Aurore` for `Aurora`), when it names a multi word company (`Tarnar Industries`), or
    when it holds a capitalised name in the middle of the sentence (`Senix` in `Precedent
    transaction Senix`) that is not a place, a month or a metric. A sentence that names nobody
    returns False: the page it comes from says whom it is about.
    """
    if not wanted:
        return False
    tokens_in_sentence = set(tokenize(sentence))
    if set(wanted) <= tokens_in_sentence:
        return False
    wanted_brand = [t for t in wanted if len(t) >= 4]
    for word in _WORD.findall(sentence):
        token = (tokenize(re.sub(r"['\u2019]s$", "", word)) or [""])[0]
        if (
            token
            and token not in wanted
            and any(_edit_distance_at_most_one(token, w) for w in wanted_brand)
        ):
            return True
    if any(looks_like_company(p) for p in entity_phrases(sentence)):
        return True
    metric_spans = [(a, b) for _, a, b in find_metrics(sentence)]
    for match in _WORD.finditer(sentence):
        start, end = match.span()
        word = re.sub(r"['\u2019]s$", "", match.group(0))
        lowered = word.lower()
        if (
            not sentence[:start].strip()  # sentence initial: a capital says nothing
            or lowered in NON_ENTITY_WORDS
            or lowered in MONTHS
            or lowered in CURRENCY_CODES
            or lowered in QUESTION_WORDS
            or _PERIOD_WORD.match(word)
            or word.isupper()
            or any(a <= start and end <= b for a, b in metric_spans)
        ):
            continue
        return True
    return False


def conflicting_entity(claim: str, evidence: str) -> str | None:
    """The company a claim names when the evidence names a different one, else None.

    A claim passes when its brand tokens are in the evidence, and also when the evidence names no
    company at all (a table chunk or a sentence that says `the company`: the title of the page
    carries the name). It fails only on positive evidence of another company: the brand is
    missing and the evidence names a multi word company (`Ithis Systems`, `Aurore Components`).
    """
    known = set(tokenize(evidence))
    for phrase in entity_phrases(claim):
        brand = distinctive_tokens(tokenize(phrase))
        if not brand or all(t in known for t in brand):
            continue
        if any(looks_like_company(other) for other in entity_phrases(evidence)):
            return phrase
    return None
