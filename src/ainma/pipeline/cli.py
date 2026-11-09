"""Command line entry point.

    python -m ainma.pipeline.cli ask --user u_analyst --deal deal_aurora "What was FY2024 revenue?"

Prints the `Answer` as JSON on stdout (the only place in `src` that writes to stdout). With
`--tiny` it loads the hand written fixture corpus into an in-memory store instead of opening the
configured store, which needs no generated data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from ainma.llm import build_mock_llm
from ainma.pipeline.ask import ask
from ainma.pipeline.config import DEFAULT_ANSWERS_LOG, PipelineConfig
from ainma.retrieval.config import RetrievalConfig
from ainma.runtime import Runtime, open_runtime
from ainma.store import SqliteStore, Store, UnknownUserError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ainma.pipeline.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    ask_cmd = commands.add_parser("ask", help="answer one question")
    ask_cmd.add_argument("question")
    ask_cmd.add_argument("--user", required=True, help="user id, for example u_analyst")
    ask_cmd.add_argument("--deal", default=None, help="deal id; omit for the general layer")
    ask_cmd.add_argument("--system", choices=["A1", "A2", "A3", "A4", "A5"], default="A5")
    ask_cmd.add_argument("--tiny", action="store_true", help="use the tiny fixture corpus")
    ask_cmd.add_argument("--log", type=Path, default=DEFAULT_ANSWERS_LOG, help="answers log path")
    ask_cmd.add_argument("--no-log", action="store_true", help="do not append to the answers log")
    return parser


async def _run_ask(args: argparse.Namespace) -> int:
    config = PipelineConfig(
        retrieval=RetrievalConfig(system=args.system),
        answers_log=None if args.no_log else args.log,
    )
    store: Store
    runtime: Runtime | None
    if args.tiny:
        from tests.fixtures.tiny import load_tiny

        store = await SqliteStore.open(":memory:")
        await load_tiny(store)
        llm = build_mock_llm()
        runtime = None
    else:
        runtime = await open_runtime()
        store, llm = runtime.store, runtime.llm
    try:
        try:
            access = await store.access_for(args.user)
        except UnknownUserError:
            sys.stderr.write(f"unknown user {args.user!r}\n")
            return 2
        answer = await ask(
            args.question, store=store, access=access, deal_id=args.deal, llm=llm, config=config
        )
        sys.stdout.write(json.dumps(answer.model_dump(mode="json"), indent=2, ensure_ascii=False))
        sys.stdout.write("\n")
        return 0
    finally:
        await (runtime.close() if runtime else store.close())


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return asyncio.run(_run_ask(args))


if __name__ == "__main__":
    raise SystemExit(main())
