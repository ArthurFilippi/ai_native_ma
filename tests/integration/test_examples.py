"""The embedded example payloads stay valid contracts and equal the shared fixtures."""

from __future__ import annotations

import json

import pytest
from pydantic import TypeAdapter

from ainma.api.examples_openapi import EXAMPLES
from ainma.contracts import Answer, BuyerCard, KpiValue, ScreeningResult
from tests.conftest import FIXTURES


@pytest.mark.parametrize(
    "name", ["answer_contradiction.json", "answer_abstention.json", "buyer_card.json"]
)
def test_copies_equal_the_fixtures(name: str) -> None:
    assert (EXAMPLES / name).read_bytes() == (FIXTURES / name).read_bytes()


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("answer_contradiction.json", Answer),
        ("answer_abstention.json", Answer),
        ("buyer_card.json", BuyerCard),
        ("screening_result.json", ScreeningResult),
        ("kpis.json", list[KpiValue]),
    ],
)
def test_examples_validate(name: str, model: type) -> None:
    TypeAdapter(model).validate_python(json.loads((EXAMPLES / name).read_text(encoding="utf-8")))
