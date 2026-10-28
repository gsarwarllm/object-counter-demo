# Object Counter: hexagonal architecture for an ML service

[![CI](https://github.com/gsarwarllm/object-counter-demo/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/gsarwarllm/object-counter-demo/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/gsarwarllm/object-counter-demo?quickstart=1)

A Flask API that receives an image and a confidence threshold, detects the objects in it with a TensorFlow Serving model, counts those at or above the threshold by class, and keeps running totals in MongoDB or PostgreSQL. It started as the homework in [`Task.md`](Task.md): show hexagonal architecture (ports and adapters) in a machine-learning system. On top of the six tasks it adds monitoring, drift detection and safe model releases, all kept outside the domain.

![Hexagonal architecture: driving adapters (Flask API, CLI; FastAPI planned) call the use cases in the core, which reach storage and models only through ports implemented by driven adapters (in-memory, MongoDB and PostgreSQL repositories, TF Serving detector)](docs/diagrams/hexagonal_architecture.png)

The domain (use cases and business rules) owns the ports; the API, the CLI, the databases and the models are adapters chosen at startup. Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## What it does

Send an image and a threshold; get back the objects found at or above it, sorted by score (a real response from the default model):

```bash
curl -F "threshold=0.5" -F "file=@resources/images/boy.jpg" http://localhost:5000/object-predictions
```

```json
{
  "count": 2,
  "model": {"name": "ssd_mobilenet_v2", "version": "1"},
  "predictions": [
    {"class_name": "person", "score": 0.994504,
     "box": {"xmin": 0.3770217, "ymin": 0.354917884, "xmax": 0.543941259, "ymax": 0.811709166}},
    {"class_name": "sports ball", "score": 0.500182271,
     "box": {"xmin": 0.599595666, "ymin": 0.620696187, "xmax": 0.619402289, "ymax": 0.648074508}}
  ],
  "threshold": 0.5
}
```

`POST /object-count` does the same detection but also adds the counts per class to the running totals and returns both. Every endpoint: [`docs/API.md`](docs/API.md).

## Quick start

| Where | How |
|---|---|
| Browser only | GitHub **Code** → **Codespaces** → **Create codespace on main**; it installs everything by itself ([details](docs/SETUP.md#fastest-github-codespaces-nothing-to-install)) |
| Ubuntu | a terminal (**Ctrl+Alt+T**); first time: [`docs/SETUP.md`](docs/SETUP.md) Parts B–D |
| Windows | **Windows Terminal** → **˅** → **Ubuntu** (WSL, with Docker Desktop running); first time: [`docs/SETUP.md`](docs/SETUP.md) Parts A, B, D |
| Windows PowerShell, Docker only | `docker compose --profile setup run --rm setup`, then `docker compose --profile app up -d --wait`: only Docker Desktop and Git needed, but no `make` targets ([details](docs/SETUP.md#windows-powershell-docker-only-no-wsl-terminal-no-make)) |

Then, in the project folder:

```bash
make setup && make run   # dev: fake model, counts in memory, no Docker (about 1 minute)
make install             # once: Python packages, MLflow, both real models, then a machine check
make start               # the real models: TF Serving, MongoDB and PostgreSQL in Docker, the app on :5000
make monitoring          # or everything in Docker, with Prometheus (:9090) and Grafana (:3000)
make demo                # the full demo, apart from your data: stack + dashboards + drift demo data + MLflow UI (:5001)
make down                # stop the containers (the counts stay saved)
```

Open [http://localhost:5000/docs](http://localhost:5000/docs) to try every endpoint in the browser; `make urls` prints every page to open, here or in a codespace ([Demo URLs](docs/DEMO-URLS.md)).

Needs: `git`, `make`, `curl` and Docker with Compose v2 (`make install-docker` on Ubuntu, Docker Desktop on Windows); `make install` installs [uv](https://docs.astral.sh/uv/), which installs Python 3.12.

| Task | Command |
|---|---|
| Fast tests (no Docker) / with coverage | `make test` / `make coverage` |
| Database, registry and end-to-end tests | `make test-integration`, `make test-models`, `make e2e E2E_COUNT_REPO=mongo` |
| Every check CI runs without Docker (lint, types, spec, security, tests) | `make check` |
| Check the machine (Docker, RAM, disk, ports, models) | `make doctor` |
| Every page to open, with this machine's or codespace's addresses | `make urls` |
| Browse the model registry | `make mlflow-ui` → [http://127.0.0.1:5001](http://127.0.0.1:5001) (`make demo` starts it in the background) |
| Release or roll back a model version | `make promote-model MODEL=... VERSION=... [ALIAS=candidate] [FORCE=1]`, then `make pull-models` ([how](docs/MODELS.md)) |
| Drift baselines, quality-gate evaluation, drift report | `make baseline`, `make evaluate MODEL=... VERSION=...`, `make drift` |
| Canary verdict and promotion | `make canary-check MODEL=...`, `make canary-promote MODEL=...` |
| Demo data for the dashboards (local stack only) | `make demo-data RESET=1`, or the whole demo in one command: `make demo` |
| Container logs | `make logs` |

Dev mode never runs a model: [what each mode really runs](docs/ARCHITECTURE.md#dev-or-prod-what-each-mode-really-runs). `make help` lists every target.

## The assignment

| Task | Answer | How to test it |
|---|---|---|
| 1. Predictions endpoint | `POST /object-predictions` ([API](docs/API.md)) | [Task 1](docs/TESTING-GUIDE.md#task-1-predictions-endpoint) |
| 2. Relational database adapter | `CountPostgresRepo`, `COUNT_REPO=postgres` ([Databases](docs/ARCHITECTURE.md#databases)) | [Task 2](docs/TESTING-GUIDE.md#task-2-postgresql-adapter) |
| 3. Code review | 33 findings with problem, impact and fix: [`docs/ANSWERS.md`](docs/ANSWERS.md#task-3-code-review-and-proposed-improvements) | [Task 3](docs/TESTING-GUIDE.md#task-3-code-review) (reading only) |
| 4. Improvements | 31 of the 33 implemented: [`docs/ANSWERS.md`](docs/ANSWERS.md#task-4-implemented-improvements) | [Task 4](docs/TESTING-GUIDE.md#task-4-improvements) |
| 5. Multiple internal models | Written answer and a working setup with an MLflow model registry: [`docs/ANSWERS.md`](docs/ANSWERS.md#task-5-multiple-internally-trained-models), [Models](docs/MODELS.md) | [Task 5](docs/TESTING-GUIDE.md#task-5-multiple-models) |
| 6(a). Integration and e2e tests | Unit to end-to-end, against real databases and the real models in CI: [`docs/TESTING.md`](docs/TESTING.md) | [Task 6](docs/TESTING-GUIDE.md#task-6-tests) |
| 6(b). Other ML frameworks | Outline with a diagram: [`docs/ANSWERS.md`](docs/ANSWERS.md#task-6b-multiple-deep-learning-frameworks-outline) | [Task 6](docs/TESTING-GUIDE.md#task-6-tests) (reading only) |

Each task is one commit: see the [commit history](https://github.com/gsarwarllm/object-counter-demo/commits/main) (oldest at the bottom, starting from the assignment as given). [`Task.md`](Task.md) ends with the status of each task and links to its commit.

## Beyond the assignment

- **Health and totals:** `GET /health`, `/health/ready`, `/object-counts`, `/models` ([API](docs/API.md))
- **Observability:** Prometheus metrics, request IDs, JSON logs, a Grafana dashboard and alerts ([Logs, metrics and dashboards](docs/OPERATIONS.md))
- **Model monitoring:** prediction and input drift against a baseline per model version, without labels ([Model monitoring](docs/OPERATIONS.md#model-monitoring-drift)), with [demo data](docs/OPERATIONS.md#demo-data) that shows every state
- **Safe releases:** a quality gate before promotion, then shadow or canary releases of a candidate version ([Shadow and canary releases](docs/MODELS.md#shadow-and-canary-releases))
- **Engineering:** CI with seven jobs (tests at every level, lint, types, security, Docker build), dependency lock files, database tuning ([CI and GitHub automation](docs/CI.md))

## Deliberately not built

These are designed in [`plan.md`](plan.md) but left as outlines, each with its reason there:

- **FastAPI** instead of Flask ([plan.md section 8](plan.md#8-optional-flask--fastapi-migration)): the architecture is already shown by several adapters on each side; rewriting working code adds risk without new behaviour.
- **Authentication** ([O1](plan.md#o1-authentication-and-authorization-p2)): not part of the assignment, and an internal service is usually protected by a gateway in front of it.
- **Feedback loop with labels** ([X7](plan.md#x7-feedback-loop)): needs labelling and a training pipeline; the models here are pretrained.
- **Other ML frameworks** (Task 6(b)): an outline, as the task allows.

## Documentation

| Document | Contents |
|---|---|
| [`docs/SETUP.md`](docs/SETUP.md) | Setup from scratch, line by line: Codespaces, Windows (WSL + Docker Desktop), Ubuntu; troubleshooting |
| [`docs/DEMO-URLS.md`](docs/DEMO-URLS.md) | Every page to open (Swagger UI, Grafana, Prometheus, TF Serving, MLflow), locally and in a codespace, and a 5-minute demo; `make urls` prints them |
| [`docs/TESTING-GUIDE.md`](docs/TESTING-GUIDE.md) | Test every task and feature by hand, step by step, with the expected results |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layers, ports and adapters, the code to read in order, dev vs prod, the two databases |
| [`docs/API.md`](docs/API.md) | Endpoints, parameters, responses and errors; the contract is [`docs/openapi.yaml`](docs/openapi.yaml) |
| [`docs/MODELS.md`](docs/MODELS.md) | The models, the MLflow registry, releasing and rolling back versions, quality gate, shadow and canary releases |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | Logs, request IDs, metrics, dashboards, drift monitoring, demo data |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | Every environment variable and its default |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Make targets, tests, dependencies |
| [`docs/CI.md`](docs/CI.md) | CI and GitHub automation: the 7 CI jobs, Dependabot, the pre-push hook, Codespaces, how a change gets into `main` |
| [`docs/TESTING.md`](docs/TESTING.md) | Testing strategy (why each level is tested) and an inventory of every test |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | The main design decisions: what was chosen, the alternatives and why |
| [`docs/ANSWERS.md`](docs/ANSWERS.md) | Written answers to Tasks 3, 4, 5 and 6(b) |
| [`plan.md`](plan.md) | The full plan: requirements, API design, every task and extension with acceptance criteria |
