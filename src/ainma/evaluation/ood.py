"""Out of distribution check: hand written documents in another vocabulary (D96).

`python -m ainma.evaluation.ood` (or `make eval-ood`) loads `eval/datasets/ood/` (5 documents of
2 deals, written by hand with words the generator never uses: net sales, turnover, FY24,
EUR 0.21bn, GM%, FTEs, order book, tables with FY22 columns), runs the five retrieval systems and
the full pipeline on its 36 questions, and writes `eval/results/OOD.md` and `ood.json`.

- Retrieval: a question is found at k when a top k passage contains one of its gold strings.
- Answer: an answerable question is right when the answer is not an abstention, and a sourced
  claim states the expected value (unit and scale normalised) or, for a non numeric question,
  cites a passage holding a gold string; an unanswerable question is right when it abstains.

36 questions give wide intervals; the point is the gap with the synthetic test split, read
together with it, not a precise score. The same author wrote these documents and the system.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ainma.contracts import ClaimStatus
from ainma.ingest.loader import load_corpus
from ainma.llm import LLM, build_mock_llm
from ainma.pipeline import PipelineConfig, ask
from ainma.retrieval import RetrievalConfig, RetrievalEngine
from ainma.retrieval.quantities import parse_quantities
from ainma.store import SqliteStore

DATASET = Path("eval/datasets/ood")
SYSTEMS = ("A1", "A2", "A3", "A4", "A5")
K = 10


class OodQuestion(BaseModel):
    id: str
    deal_id: str
    text: str
    value: float | None
    gold: list[str]
    note: str = ""


def _states(claim: str, value: float) -> bool:
    for q in parse_quantities(claim):
        if q.kind == "year":
            continue
        for candidate in (q.raw, q.value):
            if abs(candidate - value) <= 0.005 * max(abs(value), 1e-9):
                return True
    return False


async def run_ood(dataset: Path, llm: LLM) -> dict[str, Any]:
    questions = [
        OodQuestion.model_validate(q)
        for q in json.loads((dataset / "questions.json").read_text("utf-8"))
    ]
    store = await SqliteStore.open(":memory:")
    await load_corpus(store, dataset)
    access = await store.access_for("u_ood")
    engine = RetrievalEngine()
    rows: list[dict[str, Any]] = []
    try:
        for q in questions:
            row: dict[str, Any] = {"id": q.id, "note": q.note, "answerable": bool(q.gold)}
            if q.gold:
                for system in SYSTEMS:
                    result = await engine.search(
                        q.text,
                        store=store,
                        access=access,
                        deal_id=q.deal_id,
                        config=RetrievalConfig(system=system, top_k=K),
                    )
                    ranks = [
                        i
                        for i, hit in enumerate(result.hits, start=1)
                        if any(g in hit.chunk.text for g in q.gold)
                    ]
                    row[system] = ranks[0] if ranks else None
            answer = await ask(
                q.text,
                store=store,
                access=access,
                deal_id=q.deal_id,
                llm=llm,
                config=PipelineConfig(answers_log=None),
                engine=engine,
            )
            sourced = [c for c in answer.claims if c.status is ClaimStatus.SOURCED]
            if not q.gold:
                correct = answer.abstained
            elif answer.abstained:
                correct = False
            elif q.value is not None:
                correct = any(_states(c.text, q.value) for c in sourced)
            else:
                correct = any(
                    any(g in cite.quote or g in cite.doc_title for g in q.gold)
                    for c in sourced
                    for cite in c.citations
                ) or any(any(g in c.text for g in q.gold) for c in sourced)
            row["abstained"] = answer.abstained
            row["correct"] = correct
            row["claims"] = [c.text for c in sourced][:3]
            rows.append(row)
    finally:
        await store.close()
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    summary: dict[str, Any] = {
        "n_answerable": len(answerable),
        "n_unanswerable": len(unanswerable),
        "provider": f"{llm.provider} {llm.model}",
        "recall_at_10": {
            s: sum(r[s] is not None for r in answerable) / len(answerable) for s in SYSTEMS
        },
        "mrr": {s: sum(1.0 / r[s] for r in answerable if r[s]) / len(answerable) for s in SYSTEMS},
        "answer_accuracy": sum(r["correct"] for r in answerable) / len(answerable),
        "false_abstention": sum(r["abstained"] for r in answerable) / len(answerable),
        "correct_abstention": sum(r["correct"] for r in unanswerable) / len(unanswerable),
    }
    return {"summary": summary, "rows": rows}


def render(result: dict[str, Any]) -> str:
    s, rows = result["summary"], result["rows"]
    lines = [
        "# Out of distribution check",
        "",
        f"Provider: {s['provider']} (offline mock: rules, not a model). Dataset: "
        "`eval/datasets/ood/`, 5 hand written documents, 2 deals, "
        f"{s['n_answerable']} answerable and {s['n_unanswerable']} unanswerable questions. "
        "Small sample, no intervals: read the gap with the synthetic test split, not the "
        "absolute values. The same author wrote these documents and the system.",
        "",
        "| System | Recall@10 | MRR |",
        "|---|---|---|",
        *[f"| {sys_} | {s['recall_at_10'][sys_]:.3f} | {s['mrr'][sys_]:.3f} |" for sys_ in SYSTEMS],
        "",
        f"- Answer accuracy (answerable, value stated in a sourced claim): "
        f"{s['answer_accuracy']:.3f}",
        f"- False abstention (answerable): {s['false_abstention']:.3f}",
        f"- Correct abstention (unanswerable): {s['correct_abstention']:.3f}",
        "",
        "| Question | What it tests | A5 rank | Abstained | Correct |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        rank = r.get("A5", "n/a") if r["answerable"] else "n/a"
        lines.append(f"| {r['id']} | {r['note']} | {rank} | {r['abstained']} | {r['correct']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="out of distribution check (D96)")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    args = parser.parse_args(argv)
    result = asyncio.run(run_ood(args.dataset, build_mock_llm()))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "ood.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    (args.out / "OOD.md").write_text(render(result), "utf-8")
    sys.stdout.write(render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
