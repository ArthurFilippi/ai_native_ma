.PHONY: install lint typecheck test check data data-all eval live-smoke demo api web label-sample judge-daily inspect

install:
	pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

typecheck:
	mypy

test:
	pytest

check: lint typecheck test

SEED ?= 1234
SEEDS ?= 5
PROVIDER ?= mock

data:
	python -m ainma.synth generate --seed $(SEED) --out data/synthetic
	python -m ainma.synth verify data/synthetic/$(SEED)

SEED_LIST ?= 1234 1 2 3 4

data-all:
	for s in $(SEED_LIST); do python -m ainma.synth generate --seed $$s --out data/synthetic || exit 1; done

eval: data-all
	python -m ainma.evaluation.run --provider $(PROVIDER) --seeds $(SEEDS)

live-smoke: data
	python -m ainma.evaluation.live_smoke --seed $(SEED)

label-sample: data
	python -m ainma.evaluation.label_sample --seed $(SEED)

judge-daily:
	python -m ainma.judge.daily

inspect:
	@test -n "$(ID)" || (echo "usage: make inspect ID=<answer id>"; exit 1)
	python -m ainma.pipeline.inspect $(ID)

api:
	python -m ainma.api

web:
	cd web && npm run dev

demo:
	bash scripts/demo.sh
