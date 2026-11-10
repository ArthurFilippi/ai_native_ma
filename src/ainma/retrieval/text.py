"""Tokenisation and sentence splitting shared by retrieval, the pipeline and the mock tasks.

Rules (the same for documents and queries, so they always agree):
- lowercase, tokens are numbers (``182.4``, ``1,234`` becomes ``1234``) or letters with trailing
  digits (``fy2024``);
- a token such as ``fy2024`` also emits its year (``2024``) so that ``in 2024`` matches ``FY2024``;
- a light plural stemmer (``revenues`` to ``revenue``, ``companies`` to ``company``);
- a small English stop list (see ``STOPWORDS``).
"""

from __future__ import annotations

import re

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "and",
        "or",
        "but",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "by",
        "with",
        "from",
        "as",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "when",
        "where",
        "why",
        "did",
        "do",
        "does",
        "has",
        "have",
        "had",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "might",
        "than",
        "then",
        "there",
        "their",
        "they",
        "them",
        "we",
        "our",
        "you",
        "your",
        "i",
        "he",
        "she",
        "his",
        "her",
        "not",
        "no",
        "yes",
        "about",
        "into",
        "over",
        "per",
        "also",
        "any",
        "all",
        "each",
        "other",
        "such",
        "only",
        "own",
        "same",
        "so",
        "too",
        "very",
        "just",
    }
)

_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+\d*")
_POSSESSIVE = re.compile(r"['\u2019]s\b")
_LETTERS_YEAR = re.compile(r"^[a-z]+((?:19|20)\d{2})$")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])|\n+")


def stem(token: str) -> str:
    """Strip a plural ending. Digits and short tokens are left alone."""
    if not token.isalpha() or len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str, *, remove_stopwords: bool = True) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN.findall(_POSSESSIVE.sub("", text.lower())):
        if raw[0].isdigit():
            tokens.append(raw.replace(",", ""))
            continue
        if remove_stopwords and raw in STOPWORDS:
            continue
        tokens.append(stem(raw))
        match = _LETTERS_YEAR.match(raw)
        if match:
            tokens.append(match.group(1))
    return tokens


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Offsets of the sentences of `text`, whitespace trimmed, so `text[a:b]` is verbatim."""
    spans: list[tuple[int, int]] = []
    starts = [0]
    ends: list[int] = []
    for match in _SENTENCE_BREAK.finditer(text):
        ends.append(match.start())
        starts.append(match.end())
    ends.append(len(text))
    for start, end in zip(starts, ends, strict=True):
        segment = text[start:end]
        stripped = segment.strip()
        if stripped:
            offset = start + len(segment) - len(segment.lstrip())
            spans.append((offset, offset + len(stripped)))
    return spans
