# Object Counter: common tasks. Run `make help` for the list.

# Optional local overrides (see .env.example)
-include .env
export

UV ?= $(or $(shell command -v uv 2>/dev/null),$(HOME)/.local/bin/uv)
VENV := .venv
PY := $(VENV)/bin/python
export PYTHONPATH := .

.DEFAULT_GOAL := help
.PHONY: help setup run run-prod download-model up down logs test test-integration lint format security check clean

help: ## Show this help
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## Create .venv (Python 3.12 via uv) and install runtime + dev dependencies
	@test -x "$(UV)" || { echo "uv not found: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
	$(UV) venv --python 3.12 $(VENV)
	$(UV) pip install --python $(PY) -r requirements-dev.txt

run: ## Dev server on :5000 with the fake detector and in-memory counts
	ENV=dev $(PY) -m counter.entrypoints.webapp

run-prod: ## Server on :5000 against the compose services (run `make up` first)
	ENV=prod $(PY) -m counter.entrypoints.webapp

download-model: ## Download the SSD MobileNet v2 model into tmp/model (skips if present)
	./scripts/download_model.sh

up: ## Start TF Serving, MongoDB and PostgreSQL in Docker and wait until they are healthy
	docker compose up -d --wait

down: ## Stop the Docker services
	docker compose down

logs: ## Follow the Docker service logs
	docker compose logs -f

test: ## Unit and API tests (no Docker needed)
	ENV=dev $(PY) -m pytest -q -m "not integration"

test-integration: ## Repo tests against real Postgres/Mongo (Docker, or TEST_POSTGRES_DSN/TEST_MONGO_HOST)
	ENV=dev $(PY) -m pytest -q -m integration

lint: ## ruff lint and format check
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

format: ## Apply ruff fixes and formatting
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

security: ## bandit and pip-audit
	$(VENV)/bin/bandit -q -c pyproject.toml -r .
	$(VENV)/bin/pip-audit -r requirements.txt

check: lint security test ## Everything CI runs (except integration tests)

clean: ## Remove caches and debug images
	rm -rf .pytest_cache .ruff_cache tmp/debug
	find . -name __pycache__ -type d -prune -not -path './$(VENV)/*' -exec rm -rf {} +
