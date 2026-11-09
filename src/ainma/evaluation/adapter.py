"""The ONE place where the harness meets the system under test.

It is the only module that imports `search`, `ask`, `run_screening` and `extract_kpis` (and the
judge and the verification checks), by name and through guarded imports. When a target is not
there, a deterministic stub answers instead and `Adapter.modes` says `stub`, so a report written
from stubs is visibly labelled as such. Everything else in `ainma.evaluation` talks to `Adapter`.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from ainma.contracts import (
    AccessContext,
    Answer,
    BuyerProfile,
    KpiValue,
    ScreeningRequest,
    ScreeningResult,
)
from ainma.evaluation import stubs
from ainma.evaluation.metrics.agreement import JUDGE_LABELS
from ainma.evaluation.metrics.numbers import numbers_covered
from ainma.evaluation.resolve import resolve
from ainma.llm import LLM
from ainma.llm.tasks import TASK_JUDGE
from ainma.store import Store

Mode = Literal["real", "stub"]

TOP_K = 30
STUB_SCREENING_CRITERIA = ("sector_focus", "geography")

# Where each target is looked up, first match wins. The orchestrator wires or corrects names here.
TARGETS: dict[str, tuple[tuple[str, str], ...]] = {
    "search": (("ainma.retrieval", "search"), ("ainma.retrieval.search", "search")),
    "ask": (("ainma.pipeline", "ask"), ("ainma.pipeline.ask", "ask")),
    "screening": (
        ("ainma.screening", "run_screening"),
        ("ainma.screening.run", "run_screening"),
    ),
    "kpi": (("ainma.kpi", "extract_kpis"), ("ainma.kpi.extract", "extract_kpis")),
    "judge_request": (("ainma.pipeline.schemas", "JudgeRequest"),),
    "judge_result": (("ainma.pipeline.schemas", "JudgeResult"),),
    "judge_prompt": (("ainma.pipeline.prompts", "JUDGE"),),
    "retrieval_config": (("ainma.retrieval", "RetrievalConfig"),),
    "retrieval_engine": (("ainma.retrieval", "RetrievalEngine"),),
    "pipeline_config": (("ainma.pipeline", "PipelineConfig"),),
    "verbatim_span": (("ainma.pipeline.verify", "verbatim_span"),),
    "numeric_match": (("ainma.pipeline.verify", "numeric_match"),),
}

# Retrieval configuration paths used by the sensitivity sweeps (first present path wins).
SWEEP_FIELDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "tier prior uniform": (("ranker", "tier_weights"), ("tier_weights",)),
    "RRF weights": (("rrf_weights",),),
    "recency half-life": (("ranker", "half_life_days"), ("half_life_days",)),
}


class AdapterError(RuntimeError):
    """The real module exists but does not accept what the harness sends."""


@dataclass(frozen=True)
class RankedChunk:
    chunk_id: str
    score: float  # final score of the source ranker
    support: float  # the score the pipeline compares with tau (see `Adapter.abstain_basis`)


@dataclass(frozen=True)
class JudgeVerdict:
    label: str  # supported | partial | unsupported
    checks_passed: bool  # verbatim span and numeric match


@dataclass(frozen=True)
class Sweep:
    name: str
    field: str | None  # RetrievalConfig field used, None when the config does not expose one
    variants: tuple[tuple[str, Mapping[str, Any]], ...]  # label and overrides, empty: not run


def _engine_kwargs(function: Any, engine: Any) -> dict[str, Any]:
    """`{"engine": engine}` when the entry point accepts one, so indexes are fitted once."""
    if engine is not None and "engine" in inspect.signature(function).parameters:
        return {"engine": engine}
    return {}


def _find(target: str) -> Any | None:
    for module, attribute in TARGETS[target]:
        found = resolve(module, attribute)
        if found is not None and not inspect.ismodule(found):
            return found
    return None


def _scaled(value: Any, factor: float) -> Any:
    if isinstance(value, dict):
        return {k: v * factor for k, v in value.items()}
    return value * factor


def _has_path(config: Any, path: tuple[str, ...]) -> bool:
    for name in path:
        if not hasattr(config, name):
            return False
        config = getattr(config, name)
    return True


def _get_path(config: Any, path: tuple[str, ...]) -> Any:
    for name in path:
        config = getattr(config, name)
    return config


def _override(config: Any, path: tuple[str, ...], value: Any) -> dict[str, Any]:
    """Top level overrides that replace the value at `path` (nested configs are copied)."""
    head, *rest = path
    if not rest:
        return {head: value}
    child = getattr(config, head)
    return {head: child.model_copy(update=_override(child, tuple(rest), value))}


def _rrf_variants(
    path: tuple[str, ...], value: Any, default: Any
) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(value, list | tuple) and len(value) == 2:
        return [
            ("first x2", _override(default, path, (value[0] * 2.0, value[1]))),
            ("second x2", _override(default, path, (value[0], value[1] * 2.0))),
        ]
    return []


class Adapter:
    """Typed, tiny surface: `search`, `ask`, `screen`, `kpis`, `judge`, `sweeps`, `modes`."""

    def __init__(
        self,
        *,
        store: Store,
        llm: LLM,
        buyers: Sequence[BuyerProfile] = (),
        use_real: bool = True,
        answers_log: Path | None = None,
    ) -> None:
        """`answers_log` is where the real pipeline appends every answer (`None`: no log)."""
        self._store = store
        self._llm = llm
        self._buyers = list(buyers)
        self._answers_log = answers_log
        found = {name: (_find(name) if use_real else None) for name in TARGETS}
        self._search: Any = found["search"]
        self._ask: Any = found["ask"]
        self._screening: Any = found["screening"]
        self._kpi: Any = found["kpi"]
        self._judge_request: Any = found["judge_request"]
        self._judge_result: Any = found["judge_result"]
        self._judge_prompt: Any = found["judge_prompt"]
        self._retrieval_config: Any = found["retrieval_config"]
        engine_class: Any = found["retrieval_engine"]
        # One engine for the whole run: the fitted indexes are reused across queries (warm).
        self._engine: Any = engine_class() if engine_class is not None else None
        self._pipeline_config: Any = found["pipeline_config"]
        self._verbatim: Any = found["verbatim_span"]
        self._numeric: Any = found["numeric_match"]
        # `ask` and `search` are only real together with their configuration classes.
        if self._retrieval_config is None:
            self._search = None
        if self._retrieval_config is None or self._pipeline_config is None:
            self._ask = None

    @property
    def modes(self) -> dict[str, Mode]:
        def mode(real: bool) -> Mode:
            return "real" if real else "stub"

        judge = None not in (self._judge_request, self._judge_result, self._judge_prompt)
        return {
            "search": mode(self._search is not None),
            "ask": mode(self._ask is not None),
            "screening": mode(self._screening is not None),
            "kpi": mode(self._kpi is not None),
            "judge": mode(judge),
            "checks": mode(self._verbatim is not None and self._numeric is not None),
        }

    @property
    def abstain_basis(self) -> str:
        """Which score the pipeline compares with tau: `relevance` or `final`."""
        if self._pipeline_config is not None:
            field = self._pipeline_config.model_fields.get("abstain_score")
            if field is not None and field.default in {"relevance", "final"}:
                return str(field.default)
        return "final"

    def config_snapshot(self) -> dict[str, Any]:
        """Default retrieval and pipeline configuration, for the configuration hash."""
        if self._search is None or self._ask is None:
            return {}
        pipeline = self._pipeline_config()
        return {
            "retrieval": self._retrieval_config().model_dump(mode="json"),
            "pipeline": pipeline.model_dump(mode="json", exclude={"answers_log"}),
            "abstain_basis": self.abstain_basis,
        }

    def backends(self) -> dict[str, str]:
        """Dense and reranker backends named in the report, `stub` when not the real search."""
        if self._search is None:
            return {"dense": "stub", "reranker": "stub"}
        config = self._retrieval_config()
        return {
            "dense": str(getattr(config, "embedder", "unknown")),
            "reranker": str(getattr(config, "reranker", "unknown")),
        }

    # ------------------------------------------------------------------ retrieval

    def _make_retrieval_config(
        self, system: str, top_k: int | None, overrides: Mapping[str, Any]
    ) -> Any:
        fields: dict[str, Any] = {"system": system, **overrides}
        if top_k is not None:
            fields["top_k"] = top_k
        unknown = sorted(set(fields) - set(self._retrieval_config.model_fields))
        if unknown:
            raise AdapterError(f"RetrievalConfig has no field(s) {unknown}")
        return self._retrieval_config(**fields)

    async def search(
        self,
        query: str,
        *,
        access: AccessContext,
        deal_id: str | None,
        system: str,
        top_k: int = TOP_K,
        overrides: Mapping[str, Any] | None = None,
    ) -> list[RankedChunk]:
        """Ranked chunks of one system (A1 to A5) for one query, access filter on."""
        if self._search is None:
            hits = await stubs.stub_search(
                query, store=self._store, access=access, deal_id=deal_id, system=system, top_k=top_k
            )
            return [RankedChunk(h.chunk.id, h.score, h.score) for h in hits]
        config = self._make_retrieval_config(system, top_k, overrides or {})
        real_hits: list[Any] = await self._search(
            query,
            store=self._store,
            access=access,
            deal_id=deal_id,
            config=config,
            **_engine_kwargs(self._search, self._engine),
        )
        basis = self.abstain_basis
        out: list[RankedChunk] = []
        for hit in real_hits:
            final = float(hit.passage.final_score)
            support = float(hit.passage.components.get(basis, final)) if basis != "final" else final
            out.append(RankedChunk(hit.chunk.id, final, support))
        return out

    def sweeps(self) -> list[Sweep]:
        """Sensitivity sweeps of the source ranker, for the fields the configuration exposes."""
        out: list[Sweep] = []
        default = self._make_retrieval_config("A5", None, {}) if self._search else None
        for name, paths in SWEEP_FIELDS.items():
            path = next((p for p in paths if default is not None and _has_path(default, p)), None)
            variants: list[tuple[str, Mapping[str, Any]]] = []
            if path is not None:
                value = _get_path(default, path)
                if name == "tier prior uniform" and isinstance(value, dict):
                    variants.append(
                        ("uniform", _override(default, path, dict.fromkeys(value, 1.0)))
                    )
                elif name == "recency half-life" and isinstance(value, dict | int | float):
                    variants += [
                        ("x0.5", _override(default, path, _scaled(value, 0.5))),
                        ("x2", _override(default, path, _scaled(value, 2.0))),
                    ]
                elif name == "RRF weights":
                    variants += _rrf_variants(path, value, default)
            out.append(Sweep(name, ".".join(path) if path else None, tuple(variants)))
        return out

    # ------------------------------------------------------------------ pipeline

    async def ask(
        self,
        question: str,
        *,
        access: AccessContext,
        deal_id: str | None,
        verifier: bool = True,
        tau: float | None = None,
    ) -> Answer:
        """The full pipeline on system A5, with or without the verifier, at threshold `tau`
        (`None` keeps the pipeline default)."""
        if self._ask is None:
            return await stubs.stub_ask(
                question,
                store=self._store,
                access=access,
                deal_id=deal_id,
                verifier=verifier,
                tau=tau,
            )
        fields: dict[str, Any] = {
            "retrieval": self._make_retrieval_config("A5", None, {}),
            "verifier": verifier,
        }
        if tau is not None:
            fields["tau"] = tau
        known = self._pipeline_config.model_fields
        if "answers_log" in known:
            fields["answers_log"] = self._answers_log
        unknown = sorted(set(fields) - set(known))
        if unknown:
            raise AdapterError(f"PipelineConfig has no field(s) {unknown}")
        answer = await self._ask(
            question,
            store=self._store,
            access=access,
            deal_id=deal_id,
            llm=self._llm,
            config=self._pipeline_config(**fields),
            **_engine_kwargs(self._ask, self._engine),
        )
        return cast(Answer, answer)

    # ------------------------------------------------------------------ screening, KPI

    async def screen(self, request: ScreeningRequest, *, access: AccessContext) -> ScreeningResult:
        if self._screening is None:
            return await stubs.stub_screen(request, self._buyers, STUB_SCREENING_CRITERIA)
        result = await self._screening(request, store=self._store, access=access, llm=self._llm)
        return cast(ScreeningResult, result)

    async def kpis(
        self, deal_id: str, *, access: AccessContext, periods: Sequence[str] | None = None
    ) -> list[KpiValue]:
        if self._kpi is None:
            return []  # a stub extracts nothing, every truth cell counts as missing
        values: list[KpiValue] = await self._kpi(
            deal_id, store=self._store, access=access, llm=self._llm, periods=periods
        )
        return values

    # ------------------------------------------------------------------ judge and checks

    async def judge(self, claim: str, passage: str, quote: str | None = None) -> JudgeVerdict:
        """Judge label for (claim, passage) plus the verbatim and numeric checks on the quote."""
        evidence = quote if quote is not None else passage
        if self.modes["judge"] == "stub":
            label = stubs.stub_judge_label(claim, passage)
        else:
            request = self._judge_request(claim=claim, quotes=[evidence], context=passage)
            result, _ = await self._llm.complete_json(
                task=TASK_JUDGE,
                system=self._judge_prompt,
                user=request.model_dump_json(),
                schema=self._judge_result,
                stage="judge",
            )
            label = str(result.label)
            if label not in JUDGE_LABELS:
                raise AdapterError(f"the judge returned {label!r}, not one of {JUDGE_LABELS}")
        if self._verbatim is not None and self._numeric is not None:
            verbatim = quote is None or bool(self._verbatim(quote, passage))
            numeric = bool(self._numeric(claim, evidence)[0])
        else:
            verbatim = quote is None or quote in passage
            numeric = numbers_covered(claim, [evidence])
        return JudgeVerdict(label=label, checks_passed=verbatim and numeric)
