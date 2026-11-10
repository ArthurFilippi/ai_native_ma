"""Read the raw output behind any answer: `python -m ainma.pipeline.inspect <ID>`.

Prints the full log entry (answer, trace, dropped claims) of the newest entry whose id equals or
starts with `<ID>`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from ainma.pipeline.config import DEFAULT_ANSWERS_LOG
from ainma.pipeline.log import read_entries


def find_entry(path: Path, answer_id: str) -> dict[str, object] | None:
    matches = [e for e in read_entries(path) if str(e.get("id", "")).startswith(answer_id)]
    return matches[-1] if matches else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ainma.pipeline.inspect")
    parser.add_argument("answer_id")
    parser.add_argument("--log", type=Path, default=DEFAULT_ANSWERS_LOG)
    args = parser.parse_args(argv)
    entry = find_entry(args.log, args.answer_id)
    if entry is None:
        sys.stderr.write(f"no answer {args.answer_id!r} in {args.log}\n")
        return 1
    sys.stdout.write(json.dumps(entry, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
