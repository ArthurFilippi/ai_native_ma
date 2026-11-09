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
    "judge": (("ainma.judge", "judge_claim"), ("ainma.judge.judge", "judge_claim")),
    "retrieval_config": (("ainma.retrieval", "RetrievalConfig"),),
    "pipeline_config": (("ainma.pipeline", "PipelineConfig"),),
    "verbatim_span": (("ainma.pipeline.verify", "verbatim_span"),),
    "numeric_match": (("ainma.pipeline.verify", "numeric_match"),),
}

# Retrieval configuration fields used by the sensitivity sweeps (first present name wins).
SWEEP_FIELDS: dict[str, tuple[str, ...]] = {
    "tier prior uniform": ("tier_weights", "tier_weight", "tier_prior"),
    "RRF weights": ("rrf_weights",),
    "recency half-life": (
        "half_life_days",
        "recency_half_life_days",
        "half_life_by_type",
        "half_lives",
    ),
}


class AdapterError(RuntimeError):
    """The real module exists but does not accept what the harness sends."""


@dataclass(frozen=True)
class RankedChunk:
    chunk_id: str
    score: float  # final score the pipeline would compare to tau


@dataclass(frozen=True)
class JudgeVerdict:
    label: str  # supported | partial | unsupported
    checks_passed: bool  # verbatim span and numeric match


@dataclass(frozen=True)
class Sweep:
    name: str
    field: str | None  # RetrievalConfig field used, None when the config does not expose one
    variants: tuple[tuple[str, Mapping[str, Any]], ...]  # label and overrides, empty: not run


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


class Adapter:
    """Typed, tiny surface: `search`, `ask`, `screen`, `kpis`, `judge`, `sweeps`, `modes`."""

    def __init__(
        self,
        *,
        store: Store,
        llm: LLM,
        buyers: Sequence[BuyerProfile] = (),
        use_real: bool = True,
    ) -> None:
        self._store = store
        self._llm = llm
        self._buyers = list(buyers)
        found = {name: (_find(name) if use_real else None) for name in TARGETS}
        self._search: Any = found["search"]
        self._ask: Any = found["ask"]
        self._screening: Any = found["screening"]
        self._kpi: Any = found["kpi"]
        self._judge: Any = found["judge"]
        self._retrieval_config: Any = found["retrieval_config"]
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

        return {
            "search": mode(self._search is not None),
            "ask": mode(self._ask is not None),
            "screening": mode(self._screening is not None),
            "kpi": mode(self._kpi is not None),
            "judge": mode(self._judge is not None),
            "checks": mode(self._verbatim is not None and self._numeric is not None),
        }

    # ------------------------------------------------------------------ retrieval

    def _make_retrieval_config(self, system: str, top_k: int, overrides: Mapping[str, Any]) -> Any:
        fields = {"system": system, "top_k": top_k, **overrides}
        known = self._retrieval_config.model_fields
        unknown = sorted(set(fields) - set(known))
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
            return [RankedChunk(h.chunk.id, h.score) for h in hits]
        config = self._make_retrieval_config(system, top_k, overrides or {})
        real_hits: list[Any] = await self._search(
            query, store=self._store, access=access, deal_id=deal_id, config=config
        )
        return [RankedChunk(h.chunk.id, float(h.passage.final_score)) for h in real_hits]

    def sweeps(self) -> list[Sweep]:
        """Sensitivity sweeps of the source ranker, for the fields the configuration exposes."""
        out: list[Sweep] = []
        default = self._make_retrieval_config("A5", TOP_K, {}) if self._search else None
        for name, candidates in SWEEP_FIELDS.items():
            field = next(
                (c for c in candidates if default is not None and hasattr(default, c)), None
            )
            variants: list[tuple[str, Mapping[str, Any]]] = []
            if field is not None:
                value = getattr(default, field)
                if name == "tier prior uniform" and isinstance(value, dict):
                    variants.append(("uniform", {field: dict.fromkeys(value, 1.0)}))
                elif name == "recency half-life" and isinstance(value, dict | int | float):
                    variants += [
                        ("x0.5", {field: _scaled(value, 0.5)}),
                        ("x2", {field: _scaled(value, 2.0)}),
                    ]
                elif name == "RRF weights":
                    variants += _rrf_variants(field, value)
            out.append(Sweep(name, field, tuple(variants)))
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
        known = self._pipeline_config.model_fields
        fields: dict[str, Any] = {
            "retrieval": self._make_retrieval_config("A5", 10, {}),
            "verifier": verifier,
        }
        if tau is not None:
            fields["tau"] = tau
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
        if self._judge is None:
            label = stubs.stub_judge_label(claim, passage)
        else:
            raw = await self._judge(claim, passage, llm=self._llm)
            label = str(getattr(raw, "label", raw))
            if label not in JUDGE_LABELS:
                raise AdapterError(f"the judge returned {label!r}, not one of {JUDGE_LABELS}")
        evidence = quote if quote is not None else passage
        if self._verbatim is not None and self._numeric is not None:
            verbatim = quote is None or bool(self._verbatim(quote, passage))
            numeric = bool(self._numeric(claim, evidence)[0])
        else:
            verbatim = quote is None or quote in passage
            numeric = numbers_covered(claim, [evidence])
        return JudgeVerdict(label=label, checks_passed=verbatim and numeric)


def _rrf_variants(field: str, value: Any) -> list[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, dict) and len(value) >= 2:
        keys = list(value)
        return [
            (f"{key} x2", {field: {k: v * (2.0 if k == key else 1.0) for k, v in value.items()}})
            for key in keys[:2]
        ]
    if isinstance(value, list | tuple) and len(value) == 2:
        return [
            ("first x2", {field: [value[0] * 2.0, value[1]]}),
            ("second x2", {field: [value[0], value[1] * 2.0]}),
        ]
    return []
