"""Generation, determinism, verification and the committed seed 1234 truth."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ainma.ingest import load_corpus
from ainma.store import SqliteStore
from ainma.synth.generate import generate
from ainma.synth.verify import verify_seed_dir
from ainma.truth import (
    ContradictionTruth,
    Fact,
    Query,
    split_of,
)

REPO = Path(__file__).resolve().parents[2]


def digest_tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module")
def seed_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate(1234, tmp_path_factory.mktemp("synth_a"))


def test_same_seed_gives_identical_bytes(seed_dir: Path, tmp_path: Path) -> None:
    again = generate(1234, tmp_path)
    first, second = digest_tree(seed_dir), digest_tree(again)
    assert first.keys() == second.keys()
    assert first == second


def test_different_seeds_differ(seed_dir: Path, tmp_path: Path) -> None:
    other = generate(1, tmp_path)
    a = json.loads((seed_dir / "truth" / "facts.json").read_text())
    b = json.loads((other / "truth" / "facts.json").read_text())
    assert [f["value"] for f in a] != [f["value"] for f in b]


async def test_verify_passes_for_seed_1234(seed_dir: Path) -> None:
    report = await verify_seed_dir(seed_dir)
    assert report.errors == []


async def test_verify_passes_for_another_seed(tmp_path: Path) -> None:
    report = await verify_seed_dir(generate(2, tmp_path))
    assert report.errors == []


def test_committed_truth_matches_regeneration(seed_dir: Path) -> None:
    committed = REPO / "data" / "synthetic" / "1234" / "truth"
    if not committed.exists():
        pytest.skip("seed 1234 truth is not committed in this checkout")
    assert digest_tree(committed) == digest_tree(seed_dir / "truth")


def test_demo_anchors_and_pieces(seed_dir: Path) -> None:
    facts = [
        Fact.model_validate(f) for f in json.loads((seed_dir / "truth" / "facts.json").read_text())
    ]
    quotes = {f.quote for f in facts}
    assert "Net revenue for FY2024 reached EUR 182.4 million (FY2023: EUR 168.0 million)." in quotes
    assert "Aurora booked roughly EUR 179 million of revenue in 2024." in quotes
    contradictions = [
        ContradictionTruth.model_validate(c)
        for c in json.loads((seed_dir / "truth" / "contradictions.json").read_text())
    ]
    revenue = [
        c
        for c in contradictions
        if c.kind == "contradiction"
        and c.metric == "revenue"
        and c.period == "FY2024"
        and c.deal_id == "deal_aurora"
    ]
    assert revenue and {"doc_cim", "doc_news_17"} <= set(revenue[0].document_ids)
    assert revenue[0].stronger_document_id == "doc_cim"
    kinds = {c.kind for c in contradictions}
    assert kinds == {"contradiction", "consistent_control", "superseded", "withdrawn"}
    unans = json.loads((seed_dir / "truth" / "unanswerable.json").read_text())
    assert any(u["deal_id"] == "deal_aurora" and "CEO" in u["text"] for u in unans)
    assert any(u["hard"] for u in unans) and any(not u["hard"] for u in unans)


def test_queries_split_is_hash_based_and_graded(seed_dir: Path) -> None:
    queries = [
        Query.model_validate(q)
        for q in json.loads((seed_dir / "truth" / "queries.json").read_text())
    ]
    assert len(queries) >= 150
    assert {split_of(q.id) for q in queries} == {"dev", "test"}
    assert all(2 in q.relevance.values() for q in queries)
    assert {q.kind for q in queries} >= {"single_fact", "multi_fact", "comparison"}


async def test_loader_gives_access_scoped_corpus(seed_dir: Path) -> None:
    store = await SqliteStore.open(":memory:")
    try:
        report = await load_corpus(store, seed_dir)
        assert report.documents > 250
        assert report.chunks > 400
        outsider = await store.access_for("u_outsider")
        analyst = await store.access_for("u_analyst")
        lead = await store.access_for("u_lead")
        assert await store.list_deals(outsider) == []
        assert [d.id for d in await store.list_deals(analyst)] == ["deal_aurora"]
        assert "deal_borealis" in [d.id for d in await store.list_deals(lead)]
        aurora_for_outsider = await store.candidates(outsider, deal_id="deal_aurora")
        assert all(c.deal_id is None for c in aurora_for_outsider)
        aurora_for_analyst = await store.candidates(analyst, deal_id="deal_aurora")
        assert any(c.deal_id == "deal_aurora" for c in aurora_for_analyst)
        assert all(c.deal_id in ("deal_aurora", None) for c in aurora_for_analyst)
        docs = await store.list_documents(analyst, "deal_aurora")
        spa = {d.id: d for d in docs}
        assert spa["doc_spa_draft"].status.value == "superseded"
        assert spa["doc_spa_draft"].superseded_by == "doc_spa_exec"
        assert spa["doc_pr_orig"].status.value == "withdrawn"
        assert spa["doc_cim"].n_pages == 24
        assert {1, 2, 3, 4} <= {int(d.tier) for d in docs}
    finally:
        await store.close()


async def test_verify_detects_a_corrupted_span(tmp_path: Path) -> None:
    seed = generate(3, tmp_path)
    path = seed / "truth" / "facts.json"
    facts = json.loads(path.read_text())
    facts[0]["char_start"] += 1
    path.write_text(json.dumps(facts))
    report = await verify_seed_dir(seed)
    assert any(facts[0]["id"] in e for e in report.errors)


async def test_verify_detects_a_missing_contradiction(tmp_path: Path) -> None:
    seed = generate(4, tmp_path)
    path = seed / "truth" / "contradictions.json"
    items = json.loads(path.read_text())
    items = [c for c in items if c["kind"] != "contradiction"][:5] + [
        c for c in items if c["kind"] == "contradiction"
    ][1:]
    path.write_text(json.dumps(items))
    report = await verify_seed_dir(seed)
    assert any("missing from contradictions.json" in e for e in report.errors)
