"""Live smoke run: a few real model calls through the full pipeline, reported apart from the mock.

`python -m ainma.evaluation.live_smoke --seed 1234 [--n 8]` (or `make live-smoke`) reads the
provider settings from the environment (`LLM_PROVIDER`, `LLM_MODEL`, `JUDGE_PROVIDER`,
`JUDGE_MODEL` and the key). Without a live provider and its key it writes nothing and says
`live run not executed`; it never falls back to the mock. With one, it answers the first `n`
answerable test split queries and the first unanswerable ones of the seed, and writes
`eval/results/LIVE_SMOKE.md` and `live_smoke.json`: writer and judge models, per question whether
a gold chunk was cited, claims kept and dropped by the verifier, tokens, cost and latency. It is a
smoke test of the live path, not a benchmark: `make eval PROVIDER=gemini` is the measured run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from ainma.contracts import ClaimStatus
from ainma.evaluation.groundtruth import open_seed
from ainma.llm import LLM, build_llm
from ainma.llm.factory import build_judge_llm
from ainma.pipeline import PipelineConfig, ask_detailed
from ainma.retrieval import RetrievalEngine
from ainma.settings import Settings, get_settings
from ainma.truth import split_of

NOT_EXECUTED = "live run not executed"


def live_ready(settings: Settings) -> str | None:
    """None when a live writer is configured with its key, else the reason it is not."""
    if settings.llm_provider == "mock":
        return f"{NOT_EXECUTED}: LLM_PROVIDER is mock"
    key = settings.gemini_api_key if settings.llm_provider == "gemini" else settings.openai_api_key
    if not key:
        return f"{NOT_EXECUTED}: no API key for {settings.llm_provider} in the environment"
    if settings.llm_allow_mock_fallback:
        return f"{NOT_EXECUTED}: LLM_ALLOW_MOCK_FALLBACK must be false for a live measurement"
    return None


async def run_smoke(
    seed_dir: Path, *, llm: LLM, judge: LLM | None, n: int, n_unanswerable: int
) -> dict[str, Any]:
    store, truth = await open_seed(seed_dir)
    access = truth.access()
    engine = RetrievalEngine()
    config = PipelineConfig(answers_log=None)
    rows: list[dict[str, Any]] = []
    answerable = [q for q in truth.queries if split_of(q.id) == "test"][:n]
    unanswerable = [q for q in truth.unanswerable if split_of(q.id) == "test"][:n_unanswerable]
    cases = [(q.id, q.deal_id, q.text, set(q.relevance)) for q in answerable] + [
        (q.id, q.deal_id, q.text, None) for q in unanswerable
    ]
    try:
        for query_id, deal_id, text, gold in cases:
            outcome = await ask_detailed(
                text,
                store=store,
                access=access,
                deal_id=deal_id,
                llm=llm,
                judge_llm=judge,
                config=config,
                engine=engine,
            )
            answer = outcome.answer
            cited = {c.chunk_id for claim in answer.claims for c in claim.citations}
            rows.append(
                {
                    "id": query_id,
                    "question": text,
                    "answerable": gold is not None,
                    "abstained": answer.abstained,
                    "gold_cited": bool(gold and cited & gold) if gold is not None else None,
                    "sourced_claims": sum(c.status is ClaimStatus.SOURCED for c in answer.claims),
                    "dropped_by_verifier": sum(d.stage == "verifier" for d in outcome.dropped),
                    "dropped_by_writer": sum(d.stage == "writer" for d in outcome.dropped),
                    "degraded": answer.degraded,
                    "input_tokens": answer.trace.input_tokens,
                    "output_tokens": answer.trace.output_tokens,
                    "cost_usd": answer.trace.cost_usd,
                    "latency_ms": sum(answer.trace.stage_latency_ms.values()),
                }
            )
    finally:
        await store.close()
    return {
        "writer": f"{llm.provider} {llm.model}",
        "judge": f"{judge.provider} {judge.model}" if judge else f"{llm.provider} {llm.model}",
        "seed": seed_dir.name,
        "rows": rows,
    }


def render(result: dict[str, Any]) -> str:
    rows = result["rows"]
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    lines = [
        "# Live smoke run",
        "",
        f"Writer: {result['writer']}. Judge: {result['judge']}. Seed {result['seed']}. "
        "Live provider, not the mock. A smoke test of a few queries, not a benchmark.",
        "",
        f"- Answerable queries with a gold chunk cited: "
        f"{sum(bool(r['gold_cited']) for r in answerable)} of {len(answerable)}",
        f"- Unanswerable queries abstained: "
        f"{sum(r['abstained'] for r in unanswerable)} of {len(unanswerable)}",
        f"- Claims dropped by the verifier: {sum(r['dropped_by_verifier'] for r in rows)}",
        f"- Degraded answers (must be 0): {sum(r['degraded'] for r in rows)}",
        f"- Tokens in / out: {sum(r['input_tokens'] for r in rows)} / "
        f"{sum(r['output_tokens'] for r in rows)}",
        f"- Cost: {sum(costs):.4f} USD" if costs else "- Cost: unknown (no price in prices.json)",
        "",
        "| Query | Answerable | Abstained | Gold cited | Sourced | Dropped (verifier) |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['answerable']} | {r['abstained']} | {r['gold_cited']} | "
            f"{r['sourced_claims']} | {r['dropped_by_verifier']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--unanswerable", type=int, default=4)
    args = parser.parse_args(argv)
    settings = get_settings()
    reason = live_ready(settings)
    if reason is not None:
        sys.stdout.write(reason + "\n")
        return 0
    result = asyncio.run(
        run_smoke(
            args.data / str(args.seed),
            llm=build_llm(settings),
            judge=build_judge_llm(settings),
            n=args.n,
            n_unanswerable=args.unanswerable,
        )
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "live_smoke.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    (args.out / "LIVE_SMOKE.md").write_text(render(result), "utf-8")
    sys.stdout.write(render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
