from __future__ import annotations

from ainma.truth import split_of


def test_split_is_deterministic_and_roughly_thirty_percent() -> None:
    ids = [f"q_{i:04d}" for i in range(2000)]
    first = [split_of(i) for i in ids]
    assert first == [split_of(i) for i in ids]
    share = first.count("dev") / len(first)
    assert 0.25 < share < 0.35
