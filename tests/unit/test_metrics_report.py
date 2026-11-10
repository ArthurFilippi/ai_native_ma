"""Report writer and runner: static limitations, labels, determinism, seeds, smoke run."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ainma.evaluation.report import (
    LIMITATIONS,
    LIMITATIONS_PARAGRAPH,
    METADATA_BEGIN,
    MOCK_LABEL,
    TIMING_BEGIN,
    strip_run_dependent,
)
from ainma.evaluation.run import config_hash, main, parse_seeds


@pytest.fixture(scope="module")
def smoke_out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("smoke")
    assert (
        main(
            [
                "--provider",
                "mock",
                "--seeds",
                "1",
                "--smoke",
                "--out",
                str(out),
                "--resamples",
                "200",
            ]
        )
        == 0
    )
    return out


def test_smoke_run_writes_both_files(smoke_out: Path) -> None:
    report = (smoke_out / "RESULTS.md").read_text(encoding="utf-8")
    latest = json.loads((smoke_out / "latest.json").read_text(encoding="utf-8"))
    assert report.startswith("# Evaluation results")
    assert latest["meta"]["smoke"] is True
    assert latest["meta"]["seeds"] == ["smoke"]
    assert set(latest["meta"]["modes"].values()) == {"stub"}
    assert latest["meta"]["config_hash"] in report
    assert latest["meta"]["label"] == MOCK_LABEL
    assert {"retrieval", "citation", "verifier", "abstention", "contradiction"} <= set(
        latest["summary"]
    )


def test_limitations_are_static_and_printed_under_every_table_section(smoke_out: Path) -> None:
    assert len(LIMITATIONS) == 7
    report = (smoke_out / "RESULTS.md").read_text(encoding="utf-8")
    sections = report.split("\n## ")[1:]
    assert len(sections) >= 9
    for body in sections:
        if "|---" in body:
            assert LIMITATIONS_PARAGRAPH in body, body.splitlines()[0]
    assert report.count(LIMITATIONS_PARAGRAPH) == len(sections)


def test_labels_for_mock_stub_and_smoke(smoke_out: Path) -> None:
    report = (smoke_out / "RESULTS.md").read_text(encoding="utf-8")
    assert f"**{MOCK_LABEL}.**" in report
    assert "STUB COMPONENTS" in report
    assert "SMOKE RUN" in report
    assert "Hand labels: not labelled yet." in report
    assert "0 cases" in report
    assert "A5 can lower pure relevance metrics by design" in report
    assert "not run" in report  # sweeps


def test_report_has_no_dashes_or_placeholders(smoke_out: Path) -> None:
    report = (smoke_out / "RESULTS.md").read_text(encoding="utf-8")
    assert "—" not in report and "–" not in report
    assert not re.search(r"\bnan\b|\binf\b", report.lower())
    assert "None" not in report


def test_metadata_and_timing_blocks_are_delimited(smoke_out: Path) -> None:
    report = (smoke_out / "RESULTS.md").read_text(encoding="utf-8")
    assert report.count(METADATA_BEGIN) == 1
    assert report.count(TIMING_BEGIN) == 1
    stripped = strip_run_dependent(report)
    assert "Git commit" not in stripped and "p50 (ms)" not in stripped


def test_rerun_is_identical_outside_the_run_dependent_blocks(
    smoke_out: Path, tmp_path: Path
) -> None:
    assert main(["--seeds", "1", "--smoke", "--out", str(tmp_path), "--resamples", "200"]) == 0
    first = strip_run_dependent((smoke_out / "RESULTS.md").read_text(encoding="utf-8"))
    second = strip_run_dependent((tmp_path / "RESULTS.md").read_text(encoding="utf-8"))
    assert first == second
    one = json.loads((smoke_out / "latest.json").read_text(encoding="utf-8"))
    two = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    for payload in (one, two):
        del payload["summary"]["performance"]
        for key in ("date", "git_commit", "machine"):
            del payload["meta"][key]
    assert one == two


def test_missing_corpus_is_a_clear_failure(tmp_path: Path) -> None:
    code = main(["--seeds", "1", "--data", str(tmp_path / "nothing"), "--out", str(tmp_path / "o")])
    assert code == 2


def test_parse_seeds() -> None:
    assert parse_seeds([5], None) == [1234, 1, 2, 3, 4]
    assert parse_seeds([1], None) == [1234]
    assert parse_seeds([7, 8], None) == [7, 8]
    assert parse_seeds([1234], None) == [1234]
    assert parse_seeds([5], "9, 10") == [9, 10]


def test_config_hash_is_stable_and_sensitive() -> None:
    base = {"provider": "mock", "seeds": ["1"], "n_resamples": 2000}
    assert config_hash(base) == config_hash(dict(reversed(list(base.items()))))
    assert config_hash(base) != config_hash({**base, "n_resamples": 1000})
    assert re.fullmatch(r"[0-9a-f]{16}", config_hash(base))


def test_header_prints_difficulty_and_tau_and_the_basis_is_described(smoke_out: Path) -> None:
    report = (smoke_out / "RESULTS.md").read_text(encoding="utf-8")
    assert "- Difficulty, seed smoke: paraphrase_rate=" in report
    assert "hard_negative_rate=" in report
    assert "Pooled dev tau recomputed in this run:" in report
    assert "Abstention score: `" in report
    assert "(m+1)th smallest" in report
    assert "largest threshold whose false abstention" not in report
    assert "best final passage score" not in report


def test_principle_table_has_abstention_precision_and_latency_rows_are_marked(
    smoke_out: Path,
) -> None:
    report = (smoke_out / "RESULTS.md").read_text(encoding="utf-8")
    section0 = report.split("## 1.")[0]
    assert "Abstention precision" in section0 and "False abstention, end to end" in section0
    assert "p50 (ms, wall clock, differs on every run)" in report
