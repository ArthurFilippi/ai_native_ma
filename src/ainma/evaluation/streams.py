"""Stream ablation: does the ranker keep the right stream on top when the streams are mixed? (D100)

`python -m ainma.evaluation.streams --seeds 5` (or `make eval-streams`), per seed, test split:

1. fact questions (`truth/queries.json`), data room and knowledge only (the base corpus);
2. the same questions after the whole news feed is filed in every deal (the mix a news-driven desk
   has), with stream weights off, then on;
3. market questions written from `truth/news_events.json` ("What has <buyer> acquired recently?",
   "Is <buyer> said to bid for <company>?"), relevance = the chunks of the items that report the
   event, after the feed is filed, stream weights off, then on.

System A5 throughout, nDCG@10 and Recall@10, 95 percent percentile intervals of a paired bootstrap
over the questions pooled across seeds. Writes `eval/results/STREAMS.md` and `streams.json`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ainma.connectors.run import document_id_for, run_market_intel
from ainma.evaluation.groundtruth import open_seed
from ainma.evaluation.metrics.retrieval import ndcg_at_k, recall_at_k
from ainma.evaluation.stats import bootstrap_weights, mean_sample, paired_bootstrap
from ainma.retrieval import RetrievalConfig, RetrievalEngine
from ainma.retrieval.config import RankerConfig
from ainma.store import Store
from ainma.truth import NewsFeedItem, split_of

SEEDS = ("1234", "1", "2", "3", "4")
K = 10


def _config(streams: bool) -> RetrievalConfig:
    return RetrievalConfig(system="A5", top_k=K, ranker=RankerConfig(use_streams=streams))


async def _score(
    engine: RetrievalEngine,
    store: Store,
    access: Any,
    questions: Sequence[tuple[str, str | None, dict[str, int]]],
    streams: bool,
) -> dict[str, list[float | None]]:
    out: dict[str, list[float | None]] = {"ndcg": [], "recall": []}
    for text, deal_id, relevance in questions:
        result = await engine.search(
            text, store=store, access=access, deal_id=deal_id, config=_config(streams)
        )
        ids = [h.chunk.id for h in result.hits]
        out["ndcg"].append(ndcg_at_k(ids, relevance, K))
        out["recall"].append(recall_at_k(ids, relevance, K))
    return out


async def _market_questions(
    store: Store, access: Any, seed_dir: Path, buyers: dict[str, str], deal_id: str
) -> list[tuple[str, str | None, dict[str, int]]]:
    events = json.loads((seed_dir / "truth" / "news_events.json").read_text("utf-8"))
    items = [
        NewsFeedItem.model_validate(i)
        for i in json.loads((seed_dir / "news" / "items.json").read_text("utf-8"))
    ]
    by_title = {i.title: i for i in items}
    out: list[tuple[str, str | None, dict[str, int]]] = []
    for event in events:
        if split_of(event["id"]) != "test":
            continue
        name = buyers.get(event["entity"], event["entity"])
        if event["kind"] == "acquisition":
            text = f"What has {name} acquired recently?"
        elif event["kind"] == "rumour":
            text = f"Is {name} reported to bid for {event['counterparty']}?"
        elif event["kind"] == "leadership_change":
            text = f"Who did {name} appoint as chief executive?"
        else:
            text = f"What price did {name} pay for {event['counterparty']}?"
        doc_ids = {
            document_id_for(by_title[t], by_title[t].entity, deal_id)
            for t in event["item_titles"]
            if t in by_title
        }
        relevance = {
            c.id: 2
            for c in await store.candidates(access, deal_id=deal_id)
            if c.document_id in doc_ids
        }
        if relevance:
            out.append((text, deal_id, relevance))
    return out


async def run_seed(seed_dir: Path) -> dict[str, dict[str, list[float | None]]]:
    store, truth = await open_seed(seed_dir)
    access = truth.access()
    engine = RetrievalEngine()
    try:
        facts = [
            (q.text, q.deal_id, dict(q.relevance))
            for q in truth.queries
            if split_of(q.id) == "test" and q.deal_id is not None
        ]
        result = {"fact_base": await _score(engine, store, access, facts, streams=False)}
        deal_ids = sorted({d.id for d in truth.deals})
        for deal_id in deal_ids:
            await run_market_intel(deal_id, store=store, access=access, seed_dir=seed_dir)
        result["fact_mixed_off"] = await _score(engine, store, access, facts, streams=False)
        result["fact_mixed_on"] = await _score(engine, store, access, facts, streams=True)
        buyers = {b.id: b.name for b in truth.buyers}
        market = await _market_questions(store, access, seed_dir, buyers, "deal_aurora")
        result["market_off"] = await _score(engine, store, access, market, streams=False)
        result["market_on"] = await _score(engine, store, access, market, streams=True)
        return result
    finally:
        await store.close()


def summarise(per_seed: dict[str, dict[str, dict[str, list[float | None]]]]) -> dict[str, Any]:
    pooled: dict[str, dict[str, list[float | None]]] = {}
    for result in per_seed.values():
        for setting, metrics in result.items():
            for metric, values in metrics.items():
                pooled.setdefault(setting, {}).setdefault(metric, []).extend(values)
    out: dict[str, Any] = {"n": {s: len(m["ndcg"]) for s, m in pooled.items()}, "pairs": {}}
    pairs = {
        "news mixed in, fact questions (weights off vs no news)": ("fact_mixed_off", "fact_base"),
        "fact questions with news, stream weights on vs off": ("fact_mixed_on", "fact_mixed_off"),
        "market questions, stream weights on vs off": ("market_on", "market_off"),
    }
    for label, (a, b) in pairs.items():
        row: dict[str, Any] = {}
        for metric in ("ndcg", "recall"):
            sa, sb = mean_sample(pooled[a][metric]), mean_sample(pooled[b][metric])
            weights = bootstrap_weights(sa.n_units, seed=7, n_resamples=2000)
            cmp = paired_bootstrap(sa, sb, weights)
            row[metric] = {"a": cmp.a, "b": cmp.b, "diff": cmp.diff}
        out["pairs"][label] = row
    return out


def _iv(interval: Any) -> str:
    if interval is None or interval.estimate is None:
        return "n/a"
    return f"{interval.estimate:.3f} [{interval.lo:.3f}, {interval.hi:.3f}]"


def render(summary: dict[str, Any], seeds: list[str]) -> str:
    lines = [
        "# Stream ablation",
        "",
        f"Mock provider, retrieval only, system A5, seeds {', '.join(seeds)}, test split. "
        "Questions pooled over the seeds; 95 percent percentile intervals of a paired bootstrap "
        "(2000 resamples). Synthetic data: read the differences, not the levels. "
        f"Questions: {json.dumps(summary['n'])}.",
        "",
        "| Comparison | nDCG@10 A | nDCG@10 B | Difference | Recall@10 difference |",
        "|---|---|---|---|---|",
    ]
    for label, row in summary["pairs"].items():
        lines.append(
            f"| {label} | {_iv(row['ndcg']['a'])} | {_iv(row['ndcg']['b'])} | "
            f"{_iv(row['ndcg']['diff'])} | {_iv(row['recall']['diff'])} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="stream ablation (D100)")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    args = parser.parse_args(argv)
    seeds = list(SEEDS[: args.seeds])
    per_seed = {s: asyncio.run(run_seed(args.data / s)) for s in seeds}
    summary = summarise(per_seed)
    args.out.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "seeds": seeds}
    (args.out / "streams.json").write_text(
        json.dumps(payload, default=str, indent=2) + "\n", encoding="utf-8"
    )
    text = render(summary, seeds)
    (args.out / "STREAMS.md").write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
