# ruff: noqa: E501
"""Verify a generated seed directory by re-deriving every truth statement from stored chunks.

The corpus is loaded into an in-memory store exactly as the application would load it. Then
spans, support sets, relevance judgments, contradiction keys, stale cases, judge labels, KPI
truth and buyer truth are recomputed from the stored text and compared with the truth files.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from ainma.contracts import (
    AccessContext,
    BuyerProfile,
    BuyerType,
    Chunk,
    Deal,
    DocStatus,
    DocType,
)
from ainma.ingest.loader import load_corpus, read_manifest
from ainma.store import SqliteStore
from ainma.synth.absent import BUYER_TOPICS, DEAL_TOPICS, GENERAL_TOPICS
from ainma.synth.common import FRESHNESS_DAYS, TOLERANCE, YEARS
from ainma.synth.finance import KPI_IDS
from ainma.truth import (
    BuyerTruth,
    ContradictionTruth,
    Fact,
    GenerationParams,
    JudgeLabel,
    KpiTruth,
    NewsFeedItem,
    Query,
    StaleCase,
    Unanswerable,
    UsersFile,
)

NUM = re.compile(r"\d[\d,]*\.?\d*")
MIN_SIZES = {
    "answerable": 150,
    "unanswerable": 40,
    "contradictions": 30,
    "controls": 30,
    "stale": 15,
    "superseded_withdrawn": 10,
    "judge": 300,
}
REG_SENTENCES = {
    "not_met": (
        "majority owned by a sovereign wealth entity",
        "significant exposure to defense contracts",
    ),
    "met": ("privately owned and has no state shareholders",),
}
MODEL_ROWS = {
    "revenue": "Revenue",
    "cogs": "Cost of goods sold",
    "ebitda": "EBITDA",
    "ebit": "EBIT",
    "net_income": "Net income",
    "operating_cash_flow": "Operating cash flow",
    "capex": "Capital expenditure",
    "cash": "Cash",
    "total_debt": "Total debt",
    "total_assets": "Total assets",
    "total_equity": "Total equity",
    "interest_expense": "Interest expense",
    "gross_profit": "Gross profit",
}


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def err(self, message: str) -> None:
        if len(self.errors) < 60:
            self.errors.append(message)
        elif len(self.errors) == 60:
            self.errors.append("... further errors suppressed")

    def info(self, message: str) -> None:
        self.lines.append(message)


def numbers(text: str) -> list[float]:
    out: list[float] = []
    for token in NUM.findall(text):
        cleaned = token.replace(",", "").rstrip(".")
        try:
            out.append(float(cleaned))
        except ValueError:
            continue
    return out


def has_value(text: str, value: float) -> bool:
    nums = numbers(text)
    return any(
        abs(n - value) < 1e-6
        or abs(n * 1000 - value) < 1e-6
        or abs(n - value) < 1e-6 * max(1.0, abs(value))
        for n in nums
    )


def _load(seed_dir: Path, name: str, adapter: TypeAdapter[Any]) -> Any:
    return adapter.validate_json((seed_dir / "truth" / f"{name}.json").read_bytes())


async def verify_seed_dir(seed_dir: Path) -> Report:
    seed_dir = Path(seed_dir)
    rep = Report()
    store = await SqliteStore.open(":memory:")
    try:
        loaded = await load_corpus(store, seed_dir)
        rep.info(f"loaded {loaded.documents} documents, {loaded.chunks} chunks")
        await _verify(seed_dir, store, rep)
    finally:
        await store.close()
    return rep


async def _verify(seed_dir: Path, store: SqliteStore, rep: Report) -> None:
    manifest = read_manifest(seed_dir)
    mdoc = {e.id: e for e in manifest}
    facts: list[Fact] = _load(seed_dir, "facts", TypeAdapter(list[Fact]))
    queries: list[Query] = _load(seed_dir, "queries", TypeAdapter(list[Query]))
    unans: list[Unanswerable] = _load(seed_dir, "unanswerable", TypeAdapter(list[Unanswerable]))
    contras: list[ContradictionTruth] = _load(
        seed_dir, "contradictions", TypeAdapter(list[ContradictionTruth])
    )
    stale: list[StaleCase] = _load(seed_dir, "stale", TypeAdapter(list[StaleCase]))
    kpis: list[KpiTruth] = _load(seed_dir, "kpi_truth", TypeAdapter(list[KpiTruth]))
    btruth: list[BuyerTruth] = _load(seed_dir, "buyer_truth", TypeAdapter(list[BuyerTruth]))
    judge: list[JudgeLabel] = _load(seed_dir, "judge_labels", TypeAdapter(list[JudgeLabel]))
    buyers: list[BuyerProfile] = _load(seed_dir, "buyers", TypeAdapter(list[BuyerProfile]))
    deals: list[Deal] = _load(seed_dir, "deals", TypeAdapter(list[Deal]))
    _load(seed_dir, "users", TypeAdapter(UsersFile))
    params: GenerationParams = _load(seed_dir, "params", TypeAdapter(GenerationParams))
    aux: dict[str, Any] = json.loads((seed_dir / "truth" / "aux.json").read_text("utf-8"))
    news: list[NewsFeedItem] = TypeAdapter(list[NewsFeedItem]).validate_json(
        (seed_dir / "news" / "items.json").read_bytes()
    )
    ref = date.fromisoformat(aux["reference_date"])
    if f"reference_date={ref.isoformat()}" not in params.generator_version:
        rep.err("params.generator_version does not state the reference date")

    lead = await store.access_for("u_lead")
    all_chunks: dict[str, Chunk] = {}
    for deal_id in [None, *[d.id for d in deals]]:
        for c in await store.candidates(lead, deal_id=deal_id):
            all_chunks[c.id] = c
    pages: dict[tuple[str, int], str] = {}

    async def page_text(doc_id: str, page: int) -> str:
        if (doc_id, page) not in pages:
            text = await store.get_page(doc_id, page, lead)
            pages[(doc_id, page)] = text or ""
        return pages[(doc_id, page)]

    chunks_by_doc: dict[str, list[Chunk]] = defaultdict(list)
    for c in all_chunks.values():
        chunks_by_doc[c.document_id].append(c)
    fact_by_id = {f.id: f for f in facts}
    if len(fact_by_id) != len(facts):
        rep.err("duplicate fact ids")

    # ---- access: outsider sees no deal chunk, analyst sees only Aurora ----------------------
    outsider = await store.access_for("u_outsider")
    for deal in deals:
        if await store.candidates(outsider, deal_id=deal.id) != list(
            await store.candidates(outsider, deal_id=None)
        ):
            rep.err(f"u_outsider can see chunks of {deal.id}")
    analyst = await store.access_for("u_analyst")
    if analyst.allowed_deal_ids != frozenset({"deal_aurora"}):
        rep.err("u_analyst must be a member of deal_aurora only")
    if lead.allowed_deal_ids != frozenset(d.id for d in deals):
        rep.err("u_lead must be a member of every deal")
    if not any(d.id == "deal_borealis" for d in deals):
        rep.err("deal_borealis missing")

    # ---- facts ----------------------------------------------------------------------------------
    occ_all: dict[str, list[dict[str, Any]]] = aux["occurrences"]
    for f in facts:
        if f.document_id not in mdoc:
            rep.err(f"{f.id}: unknown document {f.document_id}")
            continue
        if f.deal_id != mdoc[f.document_id].deal_id:
            rep.err(f"{f.id}: deal_id differs from its document")
        occs = occ_all.get(f.id)
        if not occs:
            rep.err(f"{f.id}: no occurrence recorded")
            continue
        support: set[str] = set()
        for k, o in enumerate(occs):
            text = await page_text(o["document_id"], o["page"])
            if text[o["char_start"] : o["char_end"]] != o["quote"]:
                rep.err(f"{f.id}: occurrence {k} is not the page slice at its offsets")
            if o["document_id"] != f.document_id:
                rep.err(f"{f.id}: occurrence in another document")
            for c in chunks_by_doc[o["document_id"]]:
                if (
                    c.page == o["page"]
                    and c.char_start <= o["char_start"]
                    and o["char_end"] <= c.char_end
                ):
                    support.add(c.id)
                    if o["quote"] not in c.text:
                        rep.err(f"{f.id}: chunk {c.id} does not contain the quote")
        first = occs[0]
        if (f.page, f.char_start, f.char_end, f.quote) != (
            first["page"],
            first["char_start"],
            first["char_end"],
            first["quote"],
        ):
            rep.err(f"{f.id}: primary span differs from the first occurrence")
        text = await page_text(f.document_id, f.page)
        if text[f.char_start : f.char_end] != f.quote:
            rep.err(f"{f.id}: span does not reproduce the quote from stored page text")
        if set(f.support_chunk_ids) != support or not support:
            rep.err(
                f"{f.id}: support_chunk_ids {sorted(f.support_chunk_ids)} != re-derived {sorted(support)}"
            )
        for cid in f.support_chunk_ids:
            if cid not in all_chunks:
                rep.err(f"{f.id}: support chunk {cid} not stored")
        if not has_value(f.quote, f.value):
            rep.err(f"{f.id}: value {f.value} not found in quote {f.quote!r}")
    rep.info(f"facts verified: {len(facts)}")

    # ---- relevance and queries ------------------------------------------------------------------
    cur = {e.id: e.status is DocStatus.CURRENT for e in manifest}
    groups: dict[tuple[str, str, str], list[Fact]] = defaultdict(list)
    for f in facts:
        if cur[f.document_id]:
            groups[(f.entity, f.metric, f.period)].append(f)
    qids = {q.id for q in queries}
    for q in queries:
        gold = [fact_by_id.get(g) for g in q.gold_fact_ids]
        if any(g is None for g in gold):
            rep.err(f"{q.id}: unknown gold fact")
            continue
        gold_f = [g for g in gold if g is not None]
        if any(g.deal_id != q.deal_id for g in gold_f):
            rep.err(f"{q.id}: gold fact outside the query scope")
        rel2 = {c for g in gold_f for c in g.support_chunk_ids}
        gold_ids = {g.id for g in gold_f}
        others = [
            o
            for g in gold_f
            for o in groups.get((g.entity, g.metric, g.period), [])
            if o.id not in gold_ids
        ]
        rel1 = {c for o in others for c in o.support_chunk_ids} - rel2
        expected = dict.fromkeys(rel2, 2) | dict.fromkeys(rel1, 1)
        if q.relevance != expected:
            rep.err(f"{q.id}: relevance differs from re-derived judgments")
        for cid in q.relevance:
            chunk = all_chunks.get(cid)
            if chunk is None:
                rep.err(f"{q.id}: relevance chunk {cid} not stored")
            elif chunk.deal_id not in (q.deal_id, None):
                rep.err(f"{q.id}: relevance chunk {cid} outside the query scope")
    rep.info(f"queries verified: {len(queries)}")

    # ---- unanswerable ---------------------------------------------------------------------------
    absent: dict[str, Any] = aux["absent_terms"]
    known_topics = {t.key for t in [*DEAL_TOPICS, *GENERAL_TOPICS, *BUYER_TOPICS]}
    for u in unans:
        info = absent.get(u.id)
        if info is None or info["topic"] not in known_topics:
            rep.err(f"{u.id}: no absent topic recorded")
            continue
        scope = [c for c in all_chunks.values() if c.deal_id in (u.deal_id, None)]
        for term in info["terms"]:
            hits = [c.id for c in scope if term in c.text.lower()]
            if hits:
                rep.err(f"{u.id}: absent term {term!r} occurs in {hits[:3]}")
    rep.info(f"unanswerable verified: {len(unans)}")

    # ---- contradictions -------------------------------------------------------------------------
    covered: dict[tuple[str, str, str], set[str]] = {}
    for ct in contras:
        maybe = [fact_by_id.get(i) for i in ct.fact_ids]
        if any(x is None for x in maybe):
            rep.err(f"{ct.id}: unknown fact")
            continue
        fl = [x for x in maybe if x is not None]
        if [x.document_id for x in fl] != ct.document_ids:
            rep.err(f"{ct.id}: document_ids differ from the facts")
        if len(set(ct.document_ids)) != len(ct.document_ids):
            rep.err(f"{ct.id}: two facts from the same document")
        if any((x.entity, x.metric, x.period) != (ct.entity, ct.metric, ct.period) for x in fl):
            rep.err(f"{ct.id}: facts do not share the key")
        values = [x.value for x in fl]
        spread = (max(values) - min(values)) / abs(max(values)) if max(values) else 0.0
        if ct.kind == "contradiction":
            if spread <= TOLERANCE:
                rep.err(f"{ct.id}: contradiction whose values agree")
            if len({mdoc[d].doc_type for d in ct.document_ids}) < 1:
                rep.err(f"{ct.id}: no document type")
        elif ct.kind == "consistent_control":
            if spread > TOLERANCE:
                rep.err(f"{ct.id}: control whose values differ")
        else:
            wanted = DocStatus.SUPERSEDED if ct.kind == "superseded" else DocStatus.WITHDRAWN
            old, new = ct.document_ids
            if mdoc[old].status is not wanted or mdoc[old].superseded_by != new:
                rep.err(f"{ct.id}: {ct.kind} case does not match the manifest")
            if spread <= TOLERANCE:
                rep.err(f"{ct.id}: {ct.kind} case with equal values")
        if ct.kind in ("contradiction", "consistent_control"):
            covered[(ct.entity, ct.metric, ct.period)] = set(ct.fact_ids)
            if any(not cur[d] for d in ct.document_ids):
                rep.err(f"{ct.id}: pair uses a superseded or withdrawn document")
        if ct.query_id is not None and ct.query_id not in qids:
            rep.err(f"{ct.id}: unknown query {ct.query_id}")
    for key, fs in sorted(groups.items()):
        if len({f.document_id for f in fs}) >= 2 and covered.get(key) != {f.id for f in fs}:
            rep.err(
                f"key {key} is stated by several documents but is missing from contradictions.json"
            )
    rep.info(f"contradiction keys verified: {len(contras)}")

    # ---- stale ----------------------------------------------------------------------------------
    window = {
        DocType.PRESS_ARTICLE: 180,
        DocType.PRESS_RELEASE: 180,
        DocType.DEAL_DOCUMENT: 540,
        DocType.REGULATORY_FILING: 730,
    }
    if {k.value: v for k, v in FRESHNESS_DAYS.items()} != {k.value: v for k, v in window.items()}:
        rep.err("freshness windows differ from the specification")
    all_by_key: dict[tuple[str, str, str], list[Fact]] = defaultdict(list)
    for f in facts:
        all_by_key[(f.entity, f.metric, f.period)].append(f)
    qmap = {q.id: q for q in queries}
    for s in stale:
        sf = fact_by_id.get(s.fact_id)
        sq = qmap.get(s.query_id)
        if sf is None or sq is None or sf.id not in sq.gold_fact_ids:
            rep.err(f"{s.id}: fact or query missing, or the query does not target the fact")
            continue
        for g in all_by_key[(sf.entity, sf.metric, sf.period)]:
            e = mdoc[g.document_id]
            win = window.get(e.doc_type)
            if win is None or e.published_on is None or (ref - e.published_on).days <= win:
                rep.err(f"{s.id}: supporting document {e.id} is not older than its window")
    rep.info(f"stale cases verified: {len(stale)}")

    # ---- judge labels ---------------------------------------------------------------------------
    for j in judge:
        chunk = all_chunks.get(j.chunk_id)
        if chunk is None:
            rep.err(f"{j.id}: chunk {j.chunk_id} not stored")
            continue
        if j.quote is not None and j.quote not in chunk.text:
            rep.err(f"{j.id}: quote is not in the chunk")
        claim_nums = list(numbers(re.sub(r"FY\d{4}", "", j.claim)))
        missing = [n for n in claim_nums if not has_value(chunk.text, n)]
        if j.label == "supported" and missing:
            rep.err(f"{j.id}: supported claim has numbers absent from the chunk: {missing}")
        if j.perturbation in ("altered_number", "half_true", "unrelated") and not missing:
            rep.err(f"{j.id}: {j.perturbation} claim has no number absent from the chunk")
        expect = {"none": "supported", "half_true": "partial"}.get(j.perturbation, "unsupported")
        if j.label != expect:
            rep.err(f"{j.id}: label {j.label} does not match perturbation {j.perturbation}")
    rep.info(f"judge labels verified: {len(judge)}")

    # ---- KPI truth against the financial model text -------------------------------------------------
    model_pages = (
        [await page_text("doc_model", p) for p in range(1, 4)] if "doc_model" in mdoc else []
    )
    rows: dict[str, list[str]] = {}
    for text in model_pages:
        for line in text.split("\n"):
            parts = line.split(" | ")
            if len(parts) == len(YEARS) + 1:
                rows.setdefault(parts[0], parts[1:])
    table = {(k.kpi_id, k.period): k for k in kpis}
    for kpi_id, unit, kind in KPI_IDS:
        for year in YEARS:
            row = table.get((kpi_id, year))
            if row is None:
                rep.err(f"kpi_truth missing {kpi_id} {year}")
                continue
            if (row.unit, row.kind, row.deal_id) != (unit, kind, "deal_aurora"):
                rep.err(f"kpi_truth {kpi_id} {year}: unit or kind mismatch")
            label = MODEL_ROWS.get(kpi_id)
            if (
                label is not None
                and label in rows
                and f"{row.value:.1f}" != rows[label][YEARS.index(year)]
            ):
                rep.err(
                    f"kpi_truth {kpi_id} {year}: {row.value} differs from the model cell {rows[label][YEARS.index(year)]}"
                )
    if len(kpis) != 20 * len(YEARS):
        rep.err(f"kpi_truth has {len(kpis)} rows, expected {20 * len(YEARS)}")

    def kv(kpi_id: str, year: str) -> float:
        return table[(kpi_id, year)].value

    for year in YEARS:
        checks = {
            "gross_profit": kv("revenue", year) - kv("cogs", year),
            "gross_margin": kv("gross_profit", year) / kv("revenue", year) * 100,
            "ebitda_margin": kv("ebitda", year) / kv("revenue", year) * 100,
            "net_margin": kv("net_income", year) / kv("revenue", year) * 100,
            "free_cash_flow": kv("operating_cash_flow", year) - kv("capex", year),
            "net_debt": kv("total_debt", year) - kv("cash", year),
            "leverage": kv("net_debt", year) / kv("ebitda", year),
            "interest_coverage": kv("ebit", year) / kv("interest_expense", year),
        }
        for kpi_id, expected_value in checks.items():
            if abs(kv(kpi_id, year) - expected_value) > 1e-3 * max(1.0, abs(expected_value)):
                rep.err(f"kpi_truth {kpi_id} {year}: not consistent with its inputs")
    rep.info(f"KPI truth verified: {len(kpis)} rows")

    # ---- buyer truth --------------------------------------------------------------------------------
    await _verify_buyers(rep, buyers, btruth, facts, all_chunks, mdoc, news, aux, ref)

    # ---- sizes and demo pieces -------------------------------------------------------------------------
    n_contra = sum(1 for c in contras if c.kind == "contradiction")
    n_ctrl = sum(1 for c in contras if c.kind == "consistent_control")
    n_sw = sum(1 for c in contras if c.kind in ("superseded", "withdrawn"))
    sizes = {
        "answerable": len(queries),
        "unanswerable": len(unans),
        "contradictions": n_contra,
        "controls": n_ctrl,
        "stale": len(stale),
        "superseded_withdrawn": n_sw,
        "judge": len(judge),
    }
    for name, minimum in MIN_SIZES.items():
        if sizes[name] < minimum:
            rep.err(f"size {name}: {sizes[name]} < minimum {minimum}")
    if len(buyers) != 40 or sum(1 for b in buyers if b.buyer_type is BuyerType.STRATEGIC) != 20:
        rep.err("expected 40 buyers, 20 strategic and 20 financial")
    for b in buyers:
        n_docs = sum(1 for e in manifest if e.entity_id == b.id)
        if not 3 <= n_docs <= 5:
            rep.err(f"{b.id}: {n_docs} documents, expected 3 to 5")
    if len(news) != 60:
        rep.err(f"expected 60 news items, found {len(news)}")
    kb_docs = [e for e in manifest if e.deal_id is None and e.entity_id is None]
    if not 28 <= len(kb_docs) <= 32:
        rep.err(f"general layer has {len(kb_docs)} documents, expected about 30")
    aurora_docs = [e for e in manifest if e.deal_id == "deal_aurora"]
    if not 12 <= len(aurora_docs) <= 14:
        rep.err(f"Aurora has {len(aurora_docs)} documents, expected 12 to 14")
    if (
        "doc_cim" in mdoc
        and not 20 <= len(model_pages) * 0 + (await _n_pages(store, lead, "doc_cim")) <= 25
    ):
        rep.err("CIM must have 20 to 25 pages")
    cim_rev = [
        f
        for f in facts
        if f.document_id == "doc_cim" and f.metric == "revenue" and f.period == "FY2024"
    ]
    press_rev = [
        f
        for f in facts
        if f.document_id == "doc_news_17" and f.metric == "revenue" and f.period == "FY2024"
    ]
    if (
        not cim_rev
        or not press_rev
        or abs(cim_rev[0].value - press_rev[0].value) / cim_rev[0].value <= TOLERANCE
    ):
        rep.err("Aurora FY2024 revenue contradiction (CIM vs trade press) is missing")
    elif not any(
        c.kind == "contradiction" and {cim_rev[0].id, press_rev[0].id} <= set(c.fact_ids)
        for c in contras
    ):
        rep.err("Aurora FY2024 revenue is not listed as a contradiction")
    if params.seed == 1234:
        if (
            cim_rev
            and cim_rev[0].quote
            != "Net revenue for FY2024 reached EUR 182.4 million (FY2023: EUR 168.0 million)."
        ):
            rep.err("seed 1234: CIM anchor sentence differs from the specification")
        if (
            press_rev
            and press_rev[0].quote != "Aurora booked roughly EUR 179 million of revenue in 2024."
        ):
            rep.err("seed 1234: trade press anchor sentence differs from the specification")
    if not any(
        u.deal_id == "deal_aurora" and "CEO" in u.text and "compensation" in u.text for u in unans
    ):
        rep.err("CEO compensation question for deal_aurora is missing")
    statuses = defaultdict(set)
    for t in btruth:
        statuses[t.criterion_key].add(t.status.value)
    if "unknown" not in {s for v in statuses.values() for s in v}:
        rep.err("no buyer has an unknown criterion")
    if not any(
        t.criterion_key in ("ticket_fit", "ev_ratio") and t.status.value == "not_met"
        for t in btruth
    ):
        rep.err("no buyer has a dealbreaker")
    if not any(t.criterion_key == "fund_lifecycle" and t.status.value == "unknown" for t in btruth):
        rep.err("no unlisted fund without a stated investment period end")
    rep.info("sizes: " + ", ".join(f"{k}={v}" for k, v in sizes.items()))


async def _n_pages(store: SqliteStore, access: AccessContext, doc_id: str) -> int:
    meta = await store.get_document(doc_id, access)
    return meta.n_pages if meta else 0


async def _verify_buyers(
    rep: Report,
    buyers: list[BuyerProfile],
    btruth: list[BuyerTruth],
    facts: list[Fact],
    chunks: dict[str, Chunk],
    mdoc: dict[str, Any],
    news: list[NewsFeedItem],
    aux: dict[str, Any],
    ref: date,
) -> None:
    def months(d: date) -> float:
        return (ref - d).days / 30.4375

    ev = float(aux["aurora"]["ev_eur_m"])
    equity = float(aux["aurora"]["equity_eur_m"])
    sector = aux["aurora"]["sector"]
    region = aux["aurora"]["region"]
    got: dict[tuple[str, str], str] = {
        (t.buyer_id, t.criterion_key): t.status.value for t in btruth
    }
    from ainma.synth.world import SECTORS

    label_to_key = {v.label: k for k, v in SECTORS.items()}
    fact_by_entity: dict[tuple[str, str], list[Fact]] = defaultdict(list)
    for f in facts:
        fact_by_entity[(f.entity, f.metric)].append(f)
    text_by_buyer: dict[str, str] = defaultdict(str)
    for c in chunks.values():
        if c.entity_id:
            text_by_buyer[c.entity_id] += c.text + "\n"
    for b in buyers:
        expected: dict[str, str] = {}
        expected["sector_focus"] = "met" if sector in b.sectors else "not_met"
        expected["geography"] = "met" if region in b.geographies else "not_met"
        expected["size_range"] = "met" if ev <= b.size_eur_m <= ev * 60 else "not_met"
        text = text_by_buyer[b.id]
        low = text.lower()
        if any(s in low for s in REG_SENTENCES["not_met"]):
            expected["regulatory_fdi"] = "not_met"
        elif any(s in low for s in REG_SENTENCES["met"]):
            expected["regulatory_fdi"] = "met"
        else:
            expected["regulatory_fdi"] = "unknown"
        # acquisitions evidenced in press releases and news items
        acqs: list[tuple[date, str]] = []
        for e in mdoc.values():
            if (
                e.entity_id == b.id
                and e.title.endswith("announces an acquisition")
                and e.published_on
            ):
                body = " ".join(c.text for c in chunks.values() if c.document_id == e.id)
                m = re.search(r"acquisition of .*?, a (.+?) company", body)
                if m and m.group(1) in label_to_key:
                    acqs.append((e.published_on, label_to_key[m.group(1)]))
        for item in news:
            if item.entity == b.id and item.published_on:
                m = re.search(r"The target is a (.+?) company", item.text)
                if m and m.group(1) in label_to_key:
                    acqs.append((item.published_on, label_to_key[m.group(1)]))
        if not acqs:
            expected["recent_activity"] = "unknown"
        else:
            similar = [a for a in acqs if months(a[0]) <= 36 and a[1] == sector]
            expected["recent_activity"] = "met" if similar else "not_met"
        if b.buyer_type is BuyerType.FINANCIAL:
            share = equity / b.size_eur_m
            expected["ticket_fit"] = "met" if 0.05 <= share <= 0.40 else "not_met"
            end = list(fact_by_entity[(b.name, "investment_period_end_year")])
            if b.listed:
                expected["fund_lifecycle"] = "met"
            elif end:
                expected["fund_lifecycle"] = "met" if end[0].value - ref.year >= 2 else "not_met"
            else:
                expected["fund_lifecycle"] = "unknown"
            expected["antitrust"] = "unknown"
        else:
            expected["ev_ratio"] = "not_met" if ev / b.size_eur_m > 0.60 else "met"
            if not acqs:
                expected["integration_bandwidth"] = "unknown"
            else:
                expected["integration_bandwidth"] = (
                    "met" if sum(1 for a in acqs if months(a[0]) <= 24) <= 2 else "not_met"
                )
            share_facts = fact_by_entity[(b.name, "market_share")]
            if share_facts:
                expected["antitrust"] = "not_met" if share_facts[0].value >= 35.0 else "met"
            else:
                expected["antitrust"] = "unknown"
        for key, status in expected.items():
            if got.get((b.id, key)) != status:
                rep.err(
                    f"buyer truth {b.id} {key}: stored {got.get((b.id, key))}, re-derived {status}"
                )
        extra = {k for (bid, k) in got if bid == b.id} - set(expected)
        if extra:
            rep.err(f"buyer truth {b.id}: unexpected criteria {sorted(extra)}")
    rep.info(f"buyer truth verified: {len(btruth)} rows for {len(buyers)} buyers")
