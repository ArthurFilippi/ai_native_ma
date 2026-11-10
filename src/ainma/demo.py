"""Demo helpers: `python -m ainma.demo prepare` builds the local database from the seeded corpus,
`python -m ainma.demo script` prints the five minute demo scenario."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from ainma.ingest.loader import load_corpus
from ainma.settings import get_settings
from ainma.store import SqliteStore
from ainma.synth.generate import generate

log = logging.getLogger(__name__)

SYNTHETIC_ROOT = Path("data/synthetic")

DEMO_SCRIPT = """\
AI-native M&A, five minute demo (all data synthetic, offline mock provider)

Open the web client (http://localhost:3000). The API runs on http://localhost:8000.

0:00  One sentence: "I summarise the evidence clearly and show you the sources, so that you
      can examine them and make informed decisions."
0:30  Header user switcher: u_analyst sees Project Aurora. Switch to u_outsider: the deal is
      not listed, and the API answers 404 (curl -H "X-User-Id: u_outsider"
      http://localhost:8000/deals/deal_aurora).
1:00  Ask: "What was Aurora's gross margin and how concentrated is its customer base?"
      Click a citation: the page opens with the cited span highlighted, tier chip, date.
2:00  Ask: "What was Aurora's FY2024 revenue?" Two sides appear (CIM tier 2 versus trade press
      tier 4) with their strengths. The system does not pick a winner.
2:45  Ask: "What is the CEO's compensation package?" The system abstains and says why.
3:15  Screening tab: move a weight, the ranking changes. Open a buyer card with an unknown
      criterion and one with a dealbreaker.
4:00  KPIs tab: sourced versus computed values. Click a computed value to see its inputs.
4:30  Open eval/results/RESULTS.md: ablation table with confidence intervals, citation
      precision and recall, abstention, kappa, limitations paragraph.
5:00  Close: what is deferred (see README), what is next.
"""


async def prepare(seed: int, db_path: Path) -> None:
    seed_dir = SYNTHETIC_ROOT / str(seed)
    if not (seed_dir / "manifest.json").exists():
        log.info("generating seed %d", seed)
        generate(seed, SYNTHETIC_ROOT)
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)
    store = await SqliteStore.open(db_path)
    try:
        report = await load_corpus(store, seed_dir)
    finally:
        await store.close()
    log.info("loaded %d documents, %d chunks into %s", report.documents, report.chunks, db_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo helpers.")
    parser.add_argument("command", choices=["prepare", "script"])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.command == "script":
        sys.stdout.write(DEMO_SCRIPT)
        return
    settings = get_settings()
    asyncio.run(prepare(settings.seed, settings.sqlite_path))


if __name__ == "__main__":
    main()
