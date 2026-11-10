"""Constants and seeded random streams shared by the generators."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from random import Random

from ainma.contracts import DocType

DEMO_SEED = 1234
GENERATOR_VERSION = "synth-1.0"
# Fixed "today" for freshness windows, so stale cases never depend on the wall clock.
REFERENCE_DATE = date(2025, 6, 30)
YEARS = ["FY2020", "FY2021", "FY2022", "FY2023", "FY2024"]

# Freshness windows in days by document type (spec section 7).
FRESHNESS_DAYS: dict[DocType, int] = {
    DocType.PRESS_ARTICLE: 180,
    DocType.PRESS_RELEASE: 180,
    DocType.DEAL_DOCUMENT: 540,
    DocType.REGULATORY_FILING: 730,
}

PARAPHRASE_RATE = 0.35
HARD_NEGATIVE_RATE = 0.30
TOLERANCE = 0.005  # contradiction tolerance, relative (spec section 8)


@dataclass(frozen=True)
class Params:
    seed: int
    paraphrase_rate: float = PARAPHRASE_RATE
    hard_negative_rate: float = HARD_NEGATIVE_RATE


def rng_for(seed: int, *parts: object) -> Random:
    """Independent deterministic stream per (seed, purpose). String seeding is stable across runs."""
    digest = hashlib.sha256(":".join([str(seed), *map(str, parts)]).encode()).hexdigest()
    return Random(digest)


def is_stale(doc_type: DocType, published_on: date | None) -> bool | None:
    """True when older than the window of its type at the reference date, None if no window."""
    window = FRESHNESS_DAYS.get(doc_type)
    if window is None or published_on is None:
        return None
    return (REFERENCE_DATE - published_on).days > window
