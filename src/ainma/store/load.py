"""Load a generated seed into the configured store: `python -m ainma.store.load --seed 1234`.

With `STORE_BACKEND=postgres` and `DATABASE_URL` (a Supabase project, for example) this fills the
database the API reads; with the default SQLite backend it fills `SQLITE_PATH` (D101)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from ainma.ingest.loader import load_corpus
from ainma.runtime import open_runtime
from ainma.settings import get_settings


async def _load(seed_dir: Path) -> str:
    runtime = await open_runtime(get_settings())
    try:
        report = await load_corpus(runtime.store, seed_dir)
    finally:
        await runtime.close()
    backend = runtime.settings.store_backend
    return f"loaded {report.documents} documents, {report.chunks} chunks into the {backend} store"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    args = parser.parse_args(argv)
    sys.stdout.write(asyncio.run(_load(args.data / str(args.seed))) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
