# ruff: noqa: E501
"""Ground truth derived from structured data and the resolved fact spans."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from random import Random
from typing import Any

from ainma.contracts import BuyerType, Deal, DocStatus, Membership, Role, SourceTier, User
from ainma.synth.absent import BUYER_TOPICS, DEAL_TOPICS, GENERAL_TOPICS, Topic
from ainma.synth.common import (
    GENERATOR_VERSION,
    REFERENCE_DATE,
    TOLERANCE,
    YEARS,
    is_stale,
    rng_for,
)
from ainma.synth.corpus import Corpus
from ainma.synth.finance import KPI_IDS, kpi_truth_values
from ainma.synth.lang import METRICS, claim_text, question_text
from ainma.synth.truthio import (
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
    split_of,
)
from ainma.synth.verify import has_value
from ainma.synth.world import (
    AURORA_REGION,
    AURORA_SECTOR,
    DEAL_PLAN,
    SECTORS,
    buyer_criteria,
)

Key = tuple[str, str, str]


def key_of(f: Fact) -> Key:
    return (f.entity, f.metric, f.period)


def label_of(f: Fact) -> str:
    m = METRICS[f.metric]
    return f"{f.entity} {m.label}" if m.static else f"{f.entity} {f.period} {m.label}"


@dataclass
class Truth:
    deals: list[Deal]
    users: UsersFile
    buyers: list[Any]
    facts: list[Fact]
    queries: list[Query]
    unanswerable: list[Unanswerable]
    contradictions: list[ContradictionTruth]
    stale: list[StaleCase]
    kpi: list[KpiTruth]
    buyer_truth: list[BuyerTruth]
    judge: list[JudgeLabel]
    params: GenerationParams
    aux: dict[str, Any] = field(default_factory=dict)


def agree(values: list[float]) -> bool:
    lo, hi = min(values), max(values)
    if hi == 0:
        return True
    return (hi - lo) / abs(hi) <= TOLERANCE


class Builder:
    def __init__(self, corpus: Corpus) -> None:
        self.c = corpus
        self.facts = corpus.facts
        self.by_id = {f.id: f for f in corpus.facts}
        self.rng = rng_for(corpus.params.seed, "truth")
        self.current = {s.id: s.status is DocStatus.CURRENT for s in corpus.specs}
        self.tier = {s.id: int(corpus.metas[s.id].tier) for s in corpus.specs}
        self.date = {s.id: s.published_on for s in corpus.specs}
        self.groups: dict[Key, list[Fact]] = defaultdict(list)
        for f in self.facts:
            if self.current[f.document_id]:
                self.groups[key_of(f)].append(f)
        self.all_by_key: dict[Key, list[Fact]] = defaultdict(list)
        for f in self.facts:
            self.all_by_key[key_of(f)].append(f)
        self.status: dict[Key, str] = {}
        self.contradictions: list[ContradictionTruth] = []
        self.query_for_key: dict[Key, str] = {}
        self.queries: list[Query] = []

    # ---- helpers --------------------------------------------------------------------------

    def stronger(self, facts: list[Fact]) -> str:
        best = min(
            facts,
            key=lambda f: (self.tier[f.document_id], -self.date[f.document_id].toordinal(), f.id),
        )
        return best.document_id

    def primary(self, facts: list[Fact]) -> Fact:
        return min(
            facts,
            key=lambda f: (self.tier[f.document_id], self.date[f.document_id].toordinal(), f.id),
        )

    # ---- contradictions ---------------------------------------------------------------------

    def build_contradictions(self) -> None:
        n = 0
        for key in sorted(self.groups):
            facts = self.groups[key]
            if len({f.document_id for f in facts}) < 2:
                self.status[key] = "single"
                continue
            consistent = agree([f.value for f in facts])
            self.status[key] = "control" if consistent else "contradiction"
            n += 1
            self.contradictions.append(
                ContradictionTruth(
                    id=f"c_{n:04d}",
                    kind="consistent_control" if consistent else "contradiction",
                    deal_id=facts[0].deal_id,
                    subject=label_of(facts[0]),
                    entity=key[0],
                    metric=key[1],
                    period=key[2],
                    fact_ids=[f.id for f in facts],
                    document_ids=[f.document_id for f in facts],
                    stronger_document_id=None if consistent else self.stronger(facts),
                    expected="no_contradiction" if consistent else "contradiction",
                )
            )
        for spec in self.c.specs:
            if spec.status is DocStatus.CURRENT or spec.superseded_by is None:
                continue
            for old in [f for f in self.facts if f.document_id == spec.id]:
                match = [
                    f
                    for f in self.facts
                    if f.document_id == spec.superseded_by and key_of(f) == key_of(old)
                ]
                if not match:
                    continue
                n += 1
                superseded = spec.status is DocStatus.SUPERSEDED
                self.contradictions.append(
                    ContradictionTruth(
                        id=f"c_{n:04d}",
                        kind="superseded" if superseded else "withdrawn",
                        deal_id=old.deal_id,
                        subject=label_of(old),
                        entity=old.entity,
                        metric=old.metric,
                        period=old.period,
                        fact_ids=[old.id, match[0].id],
                        document_ids=[spec.id, spec.superseded_by],
                        stronger_document_id=spec.superseded_by,
                        expected="flag_superseded" if superseded else "flag_withdrawn",
                    )
                )

    # ---- stale --------------------------------------------------------------------------------

    def stale_facts(self) -> list[Fact]:
        out: list[Fact] = []
        for f in self.facts:
            docs = {g.document_id for g in self.all_by_key[key_of(f)]}
            if all(is_stale(self.c.metas[d].doc_type, self.date[d]) is True for d in docs):
                out.append(f)
        return out

    # ---- queries --------------------------------------------------------------------------------

    def _support(self, facts: list[Fact]) -> set[str]:
        return {c for f in facts for c in f.support_chunk_ids}

    def add_query(
        self, deal_id: str | None, text: str, kind: str, gold: list[Fact], paraphrased: bool = False
    ) -> Query:
        rel2 = self._support(gold)
        others: list[Fact] = []
        gold_ids = {g.id for g in gold}
        for g in gold:
            others.extend(o for o in self.groups.get(key_of(g), []) if o.id not in gold_ids)
        rel1 = self._support(others) - rel2
        relevance = dict.fromkeys(sorted(rel2), 2) | dict.fromkeys(sorted(rel1), 1)
        q = Query(
            id=f"q_{len(self.queries) + 1:04d}",
            deal_id=deal_id,
            text=text,
            kind=kind,
            gold_fact_ids=[g.id for g in gold],
            relevance=relevance,
            paraphrased=paraphrased,
        )
        self.queries.append(q)
        return q

    def key_query(self, key: Key, rng: Random, kind_hint: str | None = None) -> Query | None:
        facts = self.groups.get(key)
        if not facts:
            return None
        gold = facts if self.status.get(key) == "contradiction" else [self.primary(facts)]
        f0 = gold[0]
        m = METRICS[f0.metric]
        hard = f0.deal_id is not None and any(
            o.deal_id == f0.deal_id
            and o.entity != f0.entity
            and o.metric == f0.metric
            and o.period == f0.period
            for o in self.facts
        )
        paraphrased = rng.random() < self.c.params.paraphrase_rate
        text = question_text(m, f0.entity, f0.period, rng, paraphrased)
        kind = "hard_negative" if hard else ("paraphrased" if paraphrased else "single_fact")
        q = self.add_query(f0.deal_id, text, kind, gold, paraphrased)
        self.query_for_key.setdefault(key, q.id)
        return q

    def build_queries(self) -> list[StaleCase]:
        rng = rng_for(self.c.params.seed, "queries")
        stale = self.stale_facts()
        stale_keys = {key_of(f) for f in stale}
        used: set[Key] = set()

        def take(key: Key) -> None:
            if key in used:
                return
            used.add(key)
            self.key_query(key, rng)

        # contradictions, superseded and withdrawn keys first, so every case has a query
        for c in self.contradictions:
            take((c.entity, c.metric, c.period))
        # per deal sample, buyers, general layer
        by_scope: dict[str, list[Key]] = defaultdict(list)
        for key, facts in sorted(self.groups.items()):
            f0 = facts[0]
            doc = self.c.spec(f0.document_id)
            scope = f0.deal_id or ("buyers" if doc.entity_id else "kb")
            if key in stale_keys or key in used:
                continue
            by_scope[scope].append(key)
        for scope, keys in sorted(by_scope.items()):
            if scope == "buyers":
                continue  # buyers handled below
            n = 22 if scope == "deal_aurora" else (20 if scope == "kb" else 8)
            pool = [k for k in keys if METRICS[k[1]].key not in ("ticket_max",)]
            for key in rng.sample(pool, min(n, len(pool))):
                take(key)
        for b in self.c.world.buyers:
            p = b.profile
            size_metric = "aum" if p.buyer_type is BuyerType.FINANCIAL else "market_cap"
            take((p.name, size_metric, "FY2024"))
            if p.buyer_type is BuyerType.FINANCIAL and int(p.id[-2:]) % 4 == 0:
                take((p.name, "ticket_min", "static"))
            if p.buyer_type is BuyerType.STRATEGIC and b.share_stated and int(p.id[-2:]) % 4 == 1:
                take((p.name, "market_share", "FY2024"))
        # stale queries
        stale_cases: list[StaleCase] = []
        for f in stale:
            q = self.add_query_for_fact(f, rng)
            stale_cases.append(
                StaleCase(id=f"s_{len(stale_cases) + 1:04d}", query_id=q.id, fact_id=f.id)
            )
        # multi fact and comparison queries per deal
        for comp in self.c.world.companies:
            cim = "doc_cim" if comp.deal_id == "deal_aurora" else f"doc_{comp.key}_cim"
            gm = self.fact_in(cim, comp.name, "gross_margin", "FY2024")
            tc = self.fact_in(cim, comp.name, "top_customer_share", "FY2024")
            if gm and tc:
                text = (
                    f"What was {comp.name}'s gross margin in FY2024, and what share of FY2024 revenue "
                    f"came from its largest customer?"
                )
                self.add_query(comp.deal_id, text, "multi_fact", [gm, tc])
            r24 = self.fact_in(cim, comp.name, "revenue", "FY2024")
            r23 = self.fact_in(cim, comp.name, "revenue", "FY2023")
            if r24 and r23:
                self.add_query(
                    comp.deal_id,
                    f"How did {comp.name}'s revenue change between FY2023 and FY2024?",
                    "comparison",
                    [r24, r23],
                )
            hc = self.fact_in(cim, comp.name, "headcount", "FY2024")
            pl = self.fact_in(cim, comp.name, "plants", "FY2024")
            if hc and pl:
                self.add_query(
                    comp.deal_id,
                    f"How many people does {comp.name} employ and over how many production sites?",
                    "multi_fact",
                    [hc, pl],
                )
        for c in self.contradictions:
            key = (c.entity, c.metric, c.period)
            c.query_id = self.query_for_key.get(key)
        return stale_cases

    def add_query_for_fact(self, f: Fact, rng: Random) -> Query:
        m = METRICS[f.metric]
        paraphrased = rng.random() < self.c.params.paraphrase_rate
        text = question_text(m, f.entity, f.period, rng, paraphrased)
        return self.add_query(
            f.deal_id, text, "paraphrased" if paraphrased else "single_fact", [f], paraphrased
        )

    def fact_in(self, doc_id: str, entity: str, metric: str, period: str) -> Fact | None:
        for f in self.facts:
            if f.document_id == doc_id and key_of(f) == (entity, metric, period):
                return f
        return None

    # ---- unanswerable -----------------------------------------------------------------------------

    def build_unanswerable(self) -> tuple[list[Unanswerable], dict[str, dict[str, Any]]]:
        out: list[Unanswerable] = []
        aux: dict[str, dict[str, Any]] = {}

        def add(deal_id: str | None, topic: Topic, entity: str) -> None:
            uid = f"un_{len(out) + 1:04d}"
            out.append(
                Unanswerable(
                    id=uid,
                    deal_id=deal_id,
                    text=topic.question.format(E=entity),
                    reason=f"Topic '{topic.key}' is not stated in any document of the corpus.",
                    hard=topic.hard,
                )
            )
            aux[uid] = {"topic": topic.key, "terms": list(topic.terms)}

        for i, comp in enumerate(self.c.world.companies):
            for j in range(4):
                add(comp.deal_id, DEAL_TOPICS[(i * 4 + j) % len(DEAL_TOPICS)], comp.name)
        for topic in GENERAL_TOPICS:
            add(None, topic, "the bank")
        for k, n in enumerate([2, 7, 11, 15, 20, 26, 31, 38]):
            b = self.c.world.buyers[n - 1]
            add(None, BUYER_TOPICS[k % len(BUYER_TOPICS)], b.profile.name)
        return out, aux

    # ---- judge labels -------------------------------------------------------------------------------

    def build_judge(self) -> list[JudgeLabel]:
        rng = rng_for(self.c.params.seed, "judge")
        pool = [f for f in self.facts if self.current[f.document_id] and f.metric != "ticket_max"]
        sample = rng.sample(pool, 68)
        names = [c.name for c in self.c.world.companies] + [
            b.profile.name for b in self.c.world.buyers
        ]
        labels: list[JudgeLabel] = []

        def chunk_text(f: Fact) -> str:
            cid = f.support_chunk_ids[0]
            return next(c.text for c in self.c.chunks[f.document_id] if c.id == cid)

        def add(claim: str, f: Fact, label: Any, pert: Any, quote: str | None) -> None:
            jid = f"jl_{len(labels) + 1:04d}"
            labels.append(
                JudgeLabel(
                    id=jid,
                    claim=claim,
                    chunk_id=f.support_chunk_ids[0],
                    label=label,
                    perturbation=pert,
                    split=split_of(jid),
                    quote=quote,
                )
            )

        def altered(f: Fact, text: str) -> float:
            m = METRICS[f.metric]
            for _ in range(60):
                if m.vkind == "year":
                    v = f.value + rng.choice([-3.0, -2.0, 2.0, 3.0])
                elif m.vkind in ("count", "weeks", "months"):
                    v = float(round(f.value * rng.choice([0.7, 0.8, 1.2, 1.35, 1.5])))
                else:
                    v = round(f.value * rng.choice([0.7, 0.8, 0.88, 1.12, 1.2, 1.35]), 1)
                if (
                    m.vkind == "year" or abs(v - f.value) / max(abs(f.value), 1e-9) > 0.05
                ) and not has_value(text, v):
                    return v
            raise RuntimeError("could not alter value")

        for f in sample:
            m = METRICS[f.metric]
            text = chunk_text(f)
            true_claim = claim_text(m, f.entity, f.period, f.value)
            add(true_claim, f, "supported", "none", f.quote)
            add(
                claim_text(m, f.entity, f.period, altered(f, text)),
                f,
                "unsupported",
                "altered_number",
                f.quote,
            )
            if m.static:
                add(
                    claim_text(m, f.entity, f.period, altered(f, text)),
                    f,
                    "unsupported",
                    "altered_number",
                    f.quote,
                )
            else:
                y = int(f.period.removeprefix("FY")) - 1
                add(
                    claim_text(m, f.entity, f"FY{y}", f.value),
                    f,
                    "unsupported",
                    "altered_period",
                    f.quote,
                )
            other = rng.choice([n for n in names if n != f.entity])
            add(
                claim_text(m, other, f.period, f.value), f, "unsupported", "altered_entity", f.quote
            )
            second = rng.choice(
                [
                    k
                    for k in ("ebitda", "headcount", "net_debt", "capex")
                    if k != f.metric and METRICS[k].label.lower() not in text.lower()
                ]
            )
            m2 = METRICS[second]
            for _ in range(40):
                v2 = (
                    float(rng.randrange(500, 5000))
                    if m2.vkind == "count"
                    else round(rng.uniform(5, 300), 1)
                )
                if not has_value(text, v2):
                    break
            period2 = "FY2024" if not m.static else "FY2024"
            half = (
                true_claim.rstrip(".")
                + " and "
                + claim_text(m2, f.entity, period2, v2)[0].lower()
                + claim_text(m2, f.entity, period2, v2)[1:]
            )
            add(half, f, "partial", "half_true", f.quote)
            candidates = [
                g
                for g in pool
                if g.document_id != f.document_id and g.entity != f.entity and g.metric != f.metric
            ]
            unrelated = rng.choice(candidates)
            for _ in range(40):
                if not has_value(text, unrelated.value):
                    break
                unrelated = rng.choice(candidates)
            add(
                claim_text(
                    METRICS[unrelated.metric], unrelated.entity, unrelated.period, unrelated.value
                ),
                f,
                "unsupported",
                "unrelated",
                None,
            )
        return labels[:]


def build_truth(corpus: Corpus) -> Truth:
    b = Builder(corpus)
    b.build_contradictions()
    stale = b.build_queries()
    unans, unans_aux = b.build_unanswerable()
    judge = b.build_judge()
    world = corpus.world
    params = corpus.params
    aurora = world.aurora

    deals = [
        Deal(
            id=d,
            name=f"Project {p}",
            sector=SECTORS[s].label,
            description="Fictional company, synthetic data room.",
            status="bids" if d == "deal_aurora" else "marketing",
        )
        for d, p, s, _ in DEAL_PLAN
    ]
    users = UsersFile(
        users=[
            User(id="u_lead", name="Lena Lead"),
            User(id="u_analyst", name="Alex Analyst"),
            User(id="u_outsider", name="Omar Outsider"),
        ],
        memberships=[Membership(deal_id=d, user_id="u_lead", role=Role.LEAD) for d, *_ in DEAL_PLAN]
        + [Membership(deal_id="deal_aurora", user_id="u_analyst", role=Role.MEMBER)],
    )
    kpi: list[KpiTruth] = []
    for year in YEARS:
        values = kpi_truth_values(aurora.fin, year)
        for kpi_id, unit, kind in KPI_IDS:
            kpi.append(
                KpiTruth(
                    deal_id="deal_aurora",
                    kpi_id=kpi_id,
                    period=year,
                    value=values[kpi_id],
                    unit=unit,
                    kind=kind,
                )
            )
    buyer_truth = [
        BuyerTruth(deal_id="deal_aurora", buyer_id=bu.profile.id, criterion_key=key, status=status)
        for bu in world.buyers
        for key, status in buyer_criteria(bu, aurora).items()
    ]
    gen_params = GenerationParams(
        seed=params.seed,
        paraphrase_rate=params.paraphrase_rate,
        hard_negative_rate=params.hard_negative_rate,
        generator_version=f"{GENERATOR_VERSION};reference_date={REFERENCE_DATE.isoformat()}",
    )
    aux: dict[str, Any] = {
        "reference_date": REFERENCE_DATE.isoformat(),
        "freshness_days": {"press": 180, "deal_document": 540, "regulatory_filing": 730},
        "occurrences": {
            fid: [
                {
                    "document_id": o.document_id,
                    "page": o.page,
                    "char_start": o.char_start,
                    "char_end": o.char_end,
                    "quote": o.quote,
                }
                for o in occs
            ]
            for fid, occs in sorted(corpus.occurrences.items())
        },
        "absent_terms": unans_aux,
        "deal_economics": {
            c.deal_id: {
                "enterprise_value_eur_m": c.ev,
                "equity_value_eur_m": c.equity,
                "sector": c.sector,
            }
            for c in world.companies
        },
        "aurora": {
            "sector": AURORA_SECTOR,
            "region": AURORA_REGION,
            "ev_eur_m": aurora.ev,
            "equity_eur_m": aurora.equity,
        },
        "tier_note": f"stronger_document_id: lowest tier number, ties broken by the later date (T{int(SourceTier.T1)} strongest)",
    }
    return Truth(
        deals=deals,
        users=users,
        buyers=[bu.profile for bu in world.buyers],
        facts=corpus.facts,
        queries=b.queries,
        unanswerable=unans,
        contradictions=b.contradictions,
        stale=stale,
        kpi=kpi,
        buyer_truth=buyer_truth,
        judge=judge,
        params=gen_params,
        aux=aux,
    )
