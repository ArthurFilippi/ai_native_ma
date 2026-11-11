"""Regression: "takes over as chief executive" is an appointment, not an acquisition."""

from __future__ import annotations

from ainma.screening.deep import _ACQUISITION


def test_an_appointment_is_not_an_acquisition() -> None:
    assert not _ACQUISITION.search("Alma Valis takes over as chief executive of Ithis Systems.")
    assert not _ACQUISITION.search("She took over as CEO in March.")


def test_takeovers_still_count() -> None:
    assert _ACQUISITION.search("Draix Industries takes over Pelord Partners.")
    assert _ACQUISITION.search("The group took over a supplier last year.")
    assert _ACQUISITION.search("Draix Industries announces the acquisition of Pelord Partners.")
