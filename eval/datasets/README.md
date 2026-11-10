# Datasets

No data is committed here. Every evaluation set is derived from the seeded generators.

```
python -m ainma.synth generate --seed 1234 --out data/synthetic     # one seed
python -m ainma.synth verify data/synthetic/1234                    # re-derive every truth span
```

`make eval` expects one directory per seed under `data/synthetic/` (`1234 1 2 3 4` by default).
Each holds the documents, a manifest and `truth/*.json`: facts, answerable queries with graded
relevance, unanswerable queries, planted contradictions and consistent controls, stale cases, KPI
truth, buyer truth, and the constructed judge labels (schemas in `src/ainma/truth.py`).
The query split is by hash of the query id (`ainma.truth.split_of`, 30 percent dev, 70 percent
test). The generation parameters actually used (`paraphrase_rate`, `hard_negative_rate`) are read
from `truth/params.json` and printed in `eval/results/latest.json`.

The smoke run (`python -m ainma.evaluation.run --smoke`) uses a tiny corpus built into
`src/ainma/evaluation/smoke.py`. It proves the flow runs and measures nothing.

Hand labels live in `eval/labels/` (`python -m ainma.evaluation.label_sample --seed 1234`, then
`--score` after filling the CSV). Confirmed failures live in `eval/regression/` as JSON lines.
