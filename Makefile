OAS_URL = https://api-baltic.transparency-dashboard.eu/api/v1/openapi/btd_api
REPORTS_URL = https://api-baltic.transparency-dashboard.eu/api/v1/reports
SPEC = spec/openapi.json
REPORTS = spec/reports.json
CATALOG = src/baltic/_catalog.py

# The spec restates the current time in its example timestamps; pin it so the
# vendored copy only changes when the API itself does.
PIN_EXAMPLES = sed -E 's/Format: `[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}`/Format: `2024-01-01T00:00`/g'

spec: ## Refresh the vendored API metadata
	curl -sSf "$(OAS_URL)" | uv run python -m json.tool | $(PIN_EXAMPLES) > $(SPEC)
	curl -sSf "$(REPORTS_URL)" | uv run python -m json.tool > $(REPORTS)

spec-check: ## Fail if the published metadata differs from the vendored copy
	@curl -sSf "$(OAS_URL)" | uv run python -m json.tool | $(PIN_EXAMPLES) > $(SPEC).live
	@curl -sSf "$(REPORTS_URL)" | uv run python -m json.tool > $(REPORTS).live
	@diff -u $(SPEC) $(SPEC).live > /dev/null && diff -u $(REPORTS) $(REPORTS).live > /dev/null && \
		echo "spec is up to date" || \
		(rm -f $(SPEC).live $(REPORTS).live; echo "spec drifted: run 'make spec catalog'"; exit 1)
	@rm -f $(SPEC).live $(REPORTS).live

catalog: ## Regenerate src/baltic/_catalog.py from the vendored metadata
	uv run python src/gen_catalog.py --spec $(SPEC) --reports $(REPORTS) --out $(CATALOG)
	uv run ruff format $(CATALOG)

# -----------------------------------------------------------

.PHONY: help sync setup clean lint format check test test-cov test-live build spec spec-check catalog
.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "} {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

clean: ## Remove caches
	rm -rf .ruff_cache .pytest_cache .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

lint: ## Lint with ruff
	uv run ruff check .

format: ## Format with ruff
	uv run ruff format .

check: ## Lint, verify formatting, type-check and audit dependencies
	uv run ruff check .
	uv run ruff format --check .
	uv run ty check
	uv run deptry .

test: ## Run tests with pytest
	uv run pytest

test-live: ## Run the end-to-end tests against the real BTD API
	uv run pytest -m live

test-cov: ## Run tests + export test results and code coverage
	uv run pytest --junitxml=tests.xml --cov-report=xml:coverage.xml --cov=src/baltic

sync: ## Sync uv.lock + Create venv and install dependencies
	uv sync --all-groups

setup: ## Check uv.lock + Create venv and install dependencies
	uv sync --all-groups --locked

build: ## Build the sdist and wheel into dist/
	rm -rf dist
	uv build
	uv run twine check --strict dist/*
