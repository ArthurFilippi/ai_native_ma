.PHONY: install lint typecheck test check data eval demo api web label-sample judge-daily inspect

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

eval:
	python -m ainma.evaluation.run --provider $(PROVIDER) --seeds $(SEEDS)

label-sample:
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
