"""Read the ground truth of one generated seed (schemas in `ainma.truth`) and load its corpus."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ainma.contracts import AccessContext, BuyerProfile, Deal
from ainma.evaluation.resolve import resolve
from ainma.store import SqliteStore, Store
from ainma.truth import (
    BuyerTruth,
    ContradictionTruth,
    Fact,
    GenerationParams,
    JudgeLabel,
    KpiTruth,
    Query,
    StaleCase,
    Unanswerable,
    UsersFile,
)


class CorpusUnavailableError(RuntimeError):
    """The corpus of a seed cannot be loaded (data directory or loader missing)."""


@dataclass(frozen=True)
class TruthBundle:
    deals: list[Deal] = field(default_factory=list)
    users: UsersFile | None = None
    buyers: list[BuyerProfile] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    queries: list[Query] = field(default_factory=list)
    unanswerable: list[Unanswerable] = field(default_factory=list)
    contradictions: list[ContradictionTruth] = field(default_factory=list)
    stale: list[StaleCase] = field(default_factory=list)
    kpi_truth: list[KpiTruth] = field(default_factory=list)
    buyer_truth: list[BuyerTruth] = field(default_factory=list)
    judge_labels: list[JudgeLabel] = field(default_factory=list)
    params: GenerationParams | None = None
    missing_files: list[str] = field(default_factory=list)
    seed_dir: Path | None = None
    aux: dict[str, Any] = field(default_factory=dict)

    def access(self) -> AccessContext:
        """The harness reads every deal and the general layer (access control has its own tests)."""
        return AccessContext(
            user_id="eval_harness",
            allowed_deal_ids=frozenset(d.id for d in self.deals),
            include_general_layer=True,
        )

    def facts_by_id(self) -> dict[str, Fact]:
        return {f.id: f for f in self.facts}

    def queries_by_id(self) -> dict[str, Query]:
        return {q.id: q for q in self.queries}


def _read[M: BaseModel](path: Path, model: type[M]) -> list[M] | None:
    if not path.exists():
        return None
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [model.model_validate(row) for row in rows]


def load_truth(seed_dir: Path) -> TruthBundle:
    """Read `truth/*.json`. A missing file gives an empty list, listed in `missing_files`."""
    truth = seed_dir / "truth"
    missing: list[str] = []

    def lst[M: BaseModel](name: str, model: type[M]) -> list[M]:
        rows = _read(truth / f"{name}.json", model)
        if rows is None:
            missing.append(f"{name}.json")
            return []
        return rows

    users_path = truth / "users.json"
    users = (
        UsersFile.model_validate_json(users_path.read_text(encoding="utf-8"))
        if users_path.exists()
        else None
    )
    params_path = truth / "params.json"
    params = (
        GenerationParams.model_validate_json(params_path.read_text(encoding="utf-8"))
        if params_path.exists()
        else None
    )
    if users is None:
        missing.append("users.json")
    aux_path = truth / "aux.json"
    aux: dict[str, Any] = (
        json.loads(aux_path.read_text(encoding="utf-8")) if aux_path.exists() else {}
    )
    return TruthBundle(
        deals=lst("deals", Deal),
        users=users,
        buyers=lst("buyers", BuyerProfile),
        facts=lst("facts", Fact),
        queries=lst("queries", Query),
        unanswerable=lst("unanswerable", Unanswerable),
        contradictions=lst("contradictions", ContradictionTruth),
        stale=lst("stale", StaleCase),
        kpi_truth=lst("kpi_truth", KpiTruth),
        buyer_truth=lst("buyer_truth", BuyerTruth),
        judge_labels=lst("judge_labels", JudgeLabel),
        params=params,
        missing_files=missing,
        seed_dir=seed_dir,
        aux=aux,
    )


async def open_seed(seed_dir: Path) -> tuple[Store, TruthBundle]:
    """Load the corpus of `seed_dir` into an in memory store and read its truth files."""
    if not (seed_dir / "truth").is_dir():
        raise CorpusUnavailableError(
            f"{seed_dir} has no truth directory: run `python -m ainma.synth generate` first"
        )
    loader = resolve("ainma.ingest.loader", "load_corpus")
    if loader is None:
        raise CorpusUnavailableError("ainma.ingest.loader.load_corpus is not available yet")
    store = await SqliteStore.open(":memory:")
    await loader(store, seed_dir)
    return store, load_truth(seed_dir)
