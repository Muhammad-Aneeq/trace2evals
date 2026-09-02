# Trace2Evals
#
# `make` is not installed on the machine this was built on (BLOCKERS.md B-002), so every target here
# is mirrored one-for-one in `make.ps1` for Windows, and this file is verified on the Linux CI runner.
#
#   make dev     backend + frontend dev servers, live reload
#   make serve   the shipped path: build the UI, then serve it from the Python package
#   make test    lint + backend tests + frontend typecheck/tests
#   make eval    the suite-integrity gate over evals/
#   make import  import the bundled fixtures
#   make dogfood the reproducible dogfood run
#   make export  export the v1 suite into exports/
#   make stats   CI-friendly label distribution and case counts

.DEFAULT_GOAL := help
.PHONY: help install dev serve build test test-backend test-frontend lint typecheck eval check-evals \
        import dogfood export stats clean up down

UV ?= uv
NPM ?= npm
PORT ?= 8765

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## install python + node dependencies (the only step needing network)
	$(UV) sync --extra dev
	$(NPM) --prefix frontend install

build: ## build the SPA into the python package
	$(NPM) --prefix frontend run build

dev: ## backend (uvicorn, reload) + frontend (vite) together
	@echo "API  -> http://127.0.0.1:$(PORT)/api/docs"
	@echo "UI   -> http://localhost:5173  (proxies /api to the backend)"
	@$(UV) run uvicorn --factory t2e.api.app:create_app --reload --port $(PORT) & \
	 $(NPM) --prefix frontend run dev; \
	 kill %1 2>/dev/null || true

serve: build ## build the UI and serve everything from one process
	$(UV) run t2e label --serve --port $(PORT)

lint: ## ruff
	$(UV) run ruff check .

typecheck: ## strict tsc over the frontend
	$(NPM) --prefix frontend run typecheck

test-backend: ## pytest
	$(UV) run pytest

test-frontend: ## vitest component tests
	$(NPM) --prefix frontend run test

test: lint test-backend typecheck test-frontend ## everything

eval: check-evals ## the evals/ gate: the exported suite must be well-formed, non-vacuous and current
	$(UV) run pytest evals/ -p no:cacheprovider

check-evals: ## the committed evals/ suite still matches what dogfood.py produces
	$(UV) run python scripts/check_evals_current.py

import: ## import the bundled synthetic fixtures
	$(UV) run t2e import fixtures/otel fixtures/langsmith

dogfood: ## import + label + build cases + export v1 into evals/
	$(UV) run python scripts/dogfood.py

export: ## export the v1 suite into exports/
	$(UV) run t2e export --version v1 --format jsonl,pytest,promptfoo --out exports

stats: ## label distribution + case counts (non-zero exit on an empty store)
	$(UV) run t2e stats

up: build ## docker-compose up (optional; spec 03 sec 12)
	docker compose up --build

down: ## docker-compose down
	docker compose down -v

clean: ## remove the local database, build output and caches
	rm -rf .t2e exports backend/src/t2e/web .pytest_cache .ruff_cache frontend/dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
