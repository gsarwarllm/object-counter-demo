# Object Counter: common tasks. Run `make help` for the list.

# Optional local overrides (see .env.example)
-include .env
export

UV ?= $(or $(shell command -v uv 2>/dev/null),$(HOME)/.local/bin/uv)
VENV := .venv
PY := $(VENV)/bin/python
# MLflow is big (~640 MB) and only needed for the model registry, so it has its own venv.
MODELS_VENV := .venv-models
MPY := $(MODELS_VENV)/bin/python
REGISTRY := scripts/model_registry.py
export PYTHONPATH := .

.DEFAULT_GOAL := help
.PHONY: help setup lock typecheck monitoring baseline drift evaluate canary-check canary-promote run run-prod setup-models models download-models publish-models pull-models promote-model mlflow-ui up down logs test coverage test-integration test-models e2e-up test-e2e e2e docs lint format security check clean

help: ## Show this help
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## Create .venv (Python 3.12 via uv) and install runtime + dev dependencies
	@test -x "$(UV)" || { echo "uv not found: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
	$(UV) venv --python 3.12 $(VENV)
	$(UV) pip install --python $(PY) -r requirements-dev.lock

# Pins every transitive package; keeps versions already locked unless requirements*.txt need others.
lock: ## Regenerate requirements.lock and requirements-dev.lock after editing requirements*.txt
	$(UV) pip compile requirements.txt --universal --python-version 3.12 -o requirements.lock -q
	$(UV) pip compile requirements-dev.txt --universal --python-version 3.12 -o requirements-dev.lock -q

run: ## Dev server on :5000 with the fake detector and in-memory counts
	ENV=dev $(PY) -m counter.entrypoints.webapp

run-prod: ## Server on :5000 against the compose services (run `make up` first)
	ENV=prod $(PY) -m counter.entrypoints.webapp

setup-models: ## Create .venv-models with MLflow for the model registry
	@test -x "$(UV)" || { echo "uv not found: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
	$(UV) venv --python 3.12 $(MODELS_VENV)
	$(UV) pip install --python $(MPY) -r requirements-models.txt -r requirements-dev.txt

models: download-models publish-models pull-models ## Download, publish to MLflow, and pull for TF Serving

download-models: ## Download the models in models/models.json into tmp/downloads (skips present ones)
	$(PY) $(REGISTRY) download

publish-models: ## Register downloaded models as new versions in the local MLflow registry
	$(MPY) $(REGISTRY) publish

pull-models: ## Pull each model's aliased version into tmp/model and write the TF Serving config
	$(MPY) $(REGISTRY) pull

promote-model: ## Point an alias at a version: make promote-model MODEL=name VERSION=2 [ALIAS=champion] [FORCE=1]
	$(MPY) $(REGISTRY) promote $(MODEL) $(VERSION) --alias $(or $(ALIAS),champion) $(if $(FORCE),--force)

baseline: ## Drift baselines: run resources/images through each served version (needs `make up`), store in MLflow
	$(MPY) $(REGISTRY) baseline $(if $(IMAGES),--images $(IMAGES))

evaluate: ## Quality gate input: make evaluate MODEL=name VERSION=2 [DATASET=file] (version served by TF Serving)
	$(MPY) $(REGISTRY) evaluate $(MODEL) $(VERSION) $(if $(DATASET),--dataset $(DATASET))

drift: ## Drift report per served model version (JSON; PREDICTION_LOG and BASELINES_DIR as for the app)
	$(PY) -m counter.entrypoints.drift

canary-check: ## Compare a released candidate with the champion in Prometheus: make canary-check MODEL=name [WINDOW=1h]
	$(PY) -m counter.entrypoints.release_check $(MODEL) --window $(or $(WINDOW),1h)

canary-promote: canary-check ## canary-check, then promote the candidate to champion (still quality-gated); then pull-models
	$(MPY) $(REGISTRY) promote $(MODEL) candidate

mlflow-ui: ## Browse the local model registry at http://127.0.0.1:5001
	MLFLOW_DISABLE_AGENT_HINT=1 $(MODELS_VENV)/bin/mlflow ui --backend-store-uri sqlite:///tmp/mlflow/registry.db --host 127.0.0.1 --port 5001

up: ## Start TF Serving, MongoDB and PostgreSQL in Docker and wait until they are healthy
	docker compose up -d --wait

down: ## Stop the Docker services (all profiles)
	docker compose --profile app --profile monitoring down

monitoring: ## Whole stack plus Prometheus (:9090) and Grafana (:3000, dashboard "Object Counter")
	docker compose --profile app --profile monitoring up -d --build --wait

logs: ## Follow the Docker service logs
	docker compose logs -f

test: ## Unit, API, contract and stub integration tests (no Docker needed, < 10 s)
	ENV=dev $(PY) -m pytest -q -m "not integration and not models and not e2e"

coverage: ## The same tests with a coverage report (fails under 90%)
	ENV=dev $(PY) -m pytest -q -m "not integration and not models and not e2e" --cov

test-integration: ## Repo tests against real Postgres/Mongo (Docker, or TEST_POSTGRES_DSN/TEST_MONGO_HOST)
	ENV=dev $(PY) -m pytest -q -m integration

test-models: ## Model registry script tests against a temporary MLflow registry (needs setup-models)
	ENV=dev $(MPY) -m pytest -q -m models

e2e-up: ## Build and start the whole stack in Docker (app, TF Serving, databases, monitoring)
	docker compose --profile app --profile monitoring up -d --build --wait

test-e2e: ## End-to-end tests against the running stack (E2E_COUNT_REPO=mongo|postgres also checks the DB)
	E2E_BASE_URL=$(or $(E2E_BASE_URL),http://localhost:5000) \
	E2E_PROMETHEUS_URL=$(or $(E2E_PROMETHEUS_URL),http://localhost:9090) \
	E2E_GRAFANA_URL=$(or $(E2E_GRAFANA_URL),http://localhost:3000) \
	$(PY) -m pytest -q -m e2e -rs

e2e: e2e-up test-e2e ## Start the stack and run the end-to-end tests (run `make models` first)

docs: ## Validate docs/openapi.yaml (served at /openapi.yaml, Swagger UI at /docs)
	$(PY) -m openapi_spec_validator docs/openapi.yaml

lint: ## ruff lint and format check
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

typecheck: ## mypy on counter/ and scripts/ (settings in pyproject.toml)
	$(VENV)/bin/mypy

format: ## Apply ruff fixes and formatting
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

security: ## bandit and pip-audit
	$(VENV)/bin/bandit -q -c pyproject.toml -r .
	$(VENV)/bin/pip-audit -r requirements.lock
	$(VENV)/bin/pip-audit -r requirements-models.txt

check: lint typecheck docs security test ## lint + types + spec + security + tests (CI also runs integration, models, e2e)

clean: ## Remove caches and debug images
	rm -rf .pytest_cache .ruff_cache tmp/debug
	find . -name __pycache__ -type d -prune -not -path './$(VENV)/*' -exec rm -rf {} +
