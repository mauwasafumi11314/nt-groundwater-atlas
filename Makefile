# NT Groundwater Stress Atlas
.DEFAULT_GOAL := help
SHELL := /bin/sh

PYTHON ?= python
COMPOSE ?= docker compose

.PHONY: help install-hooks check-hooks doctor inspect db-up db-down db-wait schema test test-strict test-fast lint fmt clean

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install-hooks: ## Install the git pre-commit data guard
	@mkdir -p .git/hooks
	@cp scripts/hooks/pre-commit .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "installed .git/hooks/pre-commit"

check-hooks: ## Fail if the pre-commit guard is not installed / is stale
	@test -x .git/hooks/pre-commit \
	  || { echo "pre-commit hook not installed - run 'make install-hooks'"; exit 1; }
	@cmp -s scripts/hooks/pre-commit .git/hooks/pre-commit \
	  || { echo "pre-commit hook is stale - run 'make install-hooks'"; exit 1; }

doctor: ## Report whether this environment can run the atlas (fails if it cannot)
	@$(PYTHON) scripts/doctor.py

inspect: ## Report the structure of everything in data/raw/ (RAW ?= data/raw)
	@$(PYTHON) scripts/inspect_raw.py $(RAW) --out outputs/raw_inventory.txt

db-up: ## Start PostGIS
	@$(COMPOSE) up -d postgis
	@$(MAKE) --no-print-directory db-wait

db-wait: ## Block until PostGIS is accepting connections
	@echo "waiting for PostGIS..."
	@for i in $$(seq 1 40); do \
	  if $(COMPOSE) exec -T postgis pg_isready -q 2>/dev/null; then echo "ready"; exit 0; fi; \
	  sleep 1; \
	done; \
	echo "PostGIS did not become ready"; exit 1

db-down: ## Stop PostGIS
	@$(COMPOSE) down

schema: ## Apply the schema to the running database
	@$(PYTHON) -c "import sys; sys.path.insert(0,'src'); \
	from ntgw.db import get_engine, apply_schema; \
	apply_schema(get_engine()); print('schema applied')"

test: check-hooks ## Run the full test suite
	@$(PYTHON) -m pytest -ra

test-strict: check-hooks ## Run the suite and fail on ANY skip (CI / provisioned env)
	@$(PYTHON) scripts/doctor.py
	@$(PYTHON) -m pytest -ra --strict-skips

test-fast: check-hooks ## Run the test suite, skipping Monte Carlo checks
	@$(PYTHON) -m pytest -ra -m "not slow"

lint: ## Lint
	@$(PYTHON) -m ruff check src tests scripts
	@$(PYTHON) -m ruff format --check src tests scripts

fmt: ## Format
	@$(PYTHON) -m ruff format src tests scripts
	@$(PYTHON) -m ruff check --fix src tests scripts

clean: ## Remove caches and build artefacts
	@rm -rf .pytest_cache .ruff_cache **/__pycache__ outputs
	@echo "cleaned"
