"""CLI: `python -m ainma.synth generate` and `python -m ainma.synth verify <seed_dir>`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from ainma.synth.common import DEMO_SEED, HARD_NEGATIVE_RATE, PARAPHRASE_RATE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ainma.synth")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="generate one seeded synthetic corpus")
    gen.add_argument("--seed", type=int, default=DEMO_SEED)
    gen.add_argument("--out", type=Path, default=Path("data/synthetic"))
    gen.add_argument("--paraphrase-rate", type=float, default=PARAPHRASE_RATE)
    gen.add_argument("--hard-negative-rate", type=float, default=HARD_NEGATIVE_RATE)
    ver = sub.add_parser("verify", help="re-derive every truth span from stored chunks")
    ver.add_argument("seed_dir", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("ainma.synth")
    if args.command == "generate":
        from ainma.synth.generate import generate

        seed_dir = generate(
            args.seed,
            args.out,
            paraphrase_rate=args.paraphrase_rate,
            hard_negative_rate=args.hard_negative_rate,
        )
        log.info("generated %s", seed_dir)
        return 0
    from ainma.synth.verify import verify_seed_dir

    report = asyncio.run(verify_seed_dir(args.seed_dir))
    for line in report.lines:
        log.info(line)
    if report.errors:
        for err in report.errors:
            log.error("FAIL: %s", err)
        log.error("verification failed: %d error(s)", len(report.errors))
        return 1
    log.info("verification passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
