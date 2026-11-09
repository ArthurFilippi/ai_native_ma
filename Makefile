.PHONY: install lint typecheck test check data eval demo api web

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

# Targets below are implemented in later phases (see CLAUDE.md).
data:
	@echo "not implemented yet: phase B, `data` agent (synthetic data generators)"; exit 1

eval:
	@echo "not implemented yet: phase B, `eval` agent (evaluation harness)"; exit 1

api:
	@echo "not implemented yet: phase B, `app` agent (API)"; exit 1

web:
	@echo "not implemented yet: phase B, `app` agent (web client)"; exit 1

demo:
	@echo "not implemented yet: phase C (reproducible demo)"; exit 1
