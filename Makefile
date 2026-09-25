.PHONY: test lint format check bench help

help:
	@echo "usagetrim developer commands:"
	@echo "  make test    - Run pytest test suite"
	@echo "  make lint    - Run ruff linter check"
	@echo "  make format  - Auto-format code with ruff"
	@echo "  make check   - Run lint + tests"
	@echo "  make bench   - Run real-world benchmark suite"

test:
	uv run pytest -v

lint:
	uv run ruff check .

format:
	uv run ruff check --fix .
	uv run ruff format .

check: lint test

bench:
	uv run python scripts/benchmark_suite.py
