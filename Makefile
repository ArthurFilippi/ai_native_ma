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

# Targets below are implemented by later milestones (see CLAUDE.md).
data:
	@echo "not implemented yet: milestone M1 (synthetic data generators)"; exit 1

eval:
	@echo "not implemented yet: milestone M3 (evaluation harness)"; exit 1

api:
	@echo "not implemented yet: milestone M2 (API)"; exit 1

web:
	@echo "not implemented yet: milestone M5 (web client)"; exit 1

demo:
	@echo "not implemented yet: milestone M5 (reproducible demo)"; exit 1
