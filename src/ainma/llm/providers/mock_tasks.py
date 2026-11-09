"""Mock routines for every LLM task. Phase A ships none: the `core` agent registers them here."""

from __future__ import annotations

from ainma.llm.mock import MockHandler


def default_mock_handlers() -> dict[str, MockHandler]:
    return {}
