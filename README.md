# NIQ Innovation Enablement - Object Counter Challenge

The goal of this repo is demonstrate how to apply Hexagonal Architecture in a ML based system.

This application consists in a Flask API that receives an image and a threshold and returns the number of objects detected in the image.

The application is composed of three layers:

- **entrypoints**: Exposes the API and receives the requests. It is also responsible for validating the requests and returning the responses.

- **adapters**: Communicates with external services. It is responsible for translating the domain objects to the external services objects and vice-versa.

- **domain**: Business logic. It is responsible for orchestrating the calls to the external services and for applying the business rules.

The models come from Google's [TensorFlow 1 Object Detection model zoo](https://github.com/tensorflow/models/blob/master/research/object_detection/g3doc/tf1_detection_zoo.md): SSD MobileNet v2 (COCO, the default) and SSDLite MobileNet v2 (COCO), which stands in for an internally trained model. They're listed in [`models/models.json`](models/models.json); see [Models](#models).

## Requirements

- Linux or macOS with `make`, `curl` and `bash` (on Windows, use WSL or see [Windows without make](#windows-without-make))
- [uv](https://docs.astral.sh/uv/), which installs Python 3.12 for you:
  `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Docker with Compose v2, only for running against the real model and database

## Quick start (no Docker)

Uses a fake detector (always one cat) and in-memory counts.

```bash
make setup   # .venv with Python 3.12, runtime + dev dependencies
make test    # unit and API tests
make run     # dev server on http://127.0.0.1:5000
```

Run `make help` to list every target.

## Run with the real models (Docker)

```bash
make setup-models     # once: .venv-models with MLflow (~640 MB)
make models           # download, publish to the local MLflow registry, pull for TF Serving
make up               # TF Serving, MongoDB and PostgreSQL, waits until healthy
make run-prod         # app on :5000 against those services
make down             # stop the services when done
```

To run the app in a container too: `docker compose --profile app up -d --build`.

### Store the counts in PostgreSQL

Counts go to MongoDB by default in prod. To use PostgreSQL instead:

```bash
COUNT_REPO=postgres make run-prod
```

The table `object_counts` is created on first use (schema in `counter/adapters/sql/001_object_counts.sql`). Increments use `INSERT ... ON CONFLICT DO UPDATE`, so concurrent requests don't lose updates. If the database is down, `/object-count` returns `503` (problem+json) and `/object-predictions` keeps working.

## Models

Several models can be served side by side. The app never downloads from a public URL at runtime: models go through a **model registry**, here a local [MLflow](https://mlflow.org/) registry (SQLite + a folder under `tmp/mlflow/`) standing in for a private company registry.

```
models/models.json ──> make download-models ──> tmp/downloads/<name>/        (stand-in for training output)
                       make publish-models  ──> MLflow registry: <name> v1, v2, ... + alias "champion"
                       make pull-models     ──> tmp/model/<name>/<version>/ + model_config.config + models.lock.json
                       make up / run-prod   ──> TF Serving serves the pinned versions; the app calls them
```

| Model | Source | Role |
|---|---|---|
| `ssd_mobilenet_v2` (default) | SSD MobileNet v2 COCO, 2018-03-29 | The original model of this project |
| `acme_shelf_detector` | SSDLite MobileNet v2 COCO, 2018-05-09 (49 MB) | Simulated internal model: public weights published under an internal name. Its label map is a copy of COCO. |

- **Adding a model:** add an entry to `models/models.json` (name, serving type, registry alias, label map, source) and its label map under `models/labels/`, then `make models`. No code changes.
- **Releasing or rolling back a version:** `make promote-model MODEL=acme_shelf_detector VERSION=2`, then `make pull-models` and restart. Publishing a new version doesn't serve it until it's promoted.
- **Browsing the registry:** `make mlflow-ui`, then open http://127.0.0.1:5001.
- **Private registry:** set `MLFLOW_TRACKING_URI` to your MLflow server (with its credentials); the same commands work.

In dev (`ENV=dev`), every model in the manifest is served by the fake detector, so model selection works without Docker.

## Call the service

**API documentation:** Swagger UI at [http://localhost:5000/docs](http://localhost:5000/docs) (try every endpoint from the browser), and the OpenAPI 3 contract at `/openapi.yaml` ([`docs/openapi.yaml`](docs/openapi.yaml)). The spec is written by hand (contract first); tests check that every documented response, status code included, matches what the app returns.

Count objects and update the running totals:

```bash
curl -F "threshold=0.9" -F "file=@resources/images/boy.jpg" http://localhost:5000/object-count
curl -F "threshold=0.9" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-count
curl -F "threshold=0.9" -F "file=@resources/images/food.jpg" http://localhost:5000/object-count
```

List the predictions with a score at or above the threshold, sorted by score (doesn't update the totals):

```bash
curl -F "threshold=0.5" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-predictions
```

Use another model with `model_name`, and list the available models with `GET /models`:

```bash
curl -F "threshold=0.5" -F "model_name=acme_shelf_detector" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-predictions
curl http://localhost:5000/models
# {"default_model": "ssd_mobilenet_v2", "models": [{"name": "acme_shelf_detector", "version": "1"}, {"name": "ssd_mobilenet_v2", "version": "1"}]}
```

Read the totals without uploading an image (sorted by class; repeat `object_class` to filter):

```bash
curl http://localhost:5000/object-counts
curl "http://localhost:5000/object-counts?object_class=cat&object_class=dog"
# {"total_objects": [{"object_class": "cat", "count": 3}, {"object_class": "dog", "count": 1}]}
```

Health checks, for Docker, Kubernetes or a load balancer:

```bash
curl http://localhost:5000/health        # liveness: {"status": "ok"}, no dependencies checked
curl http://localhost:5000/health/ready  # readiness: 200, or 503 if the count store or a model isn't ready
# {"status": "ok", "checks": {"repository": "ok", "detectors": {"acme_shelf_detector": "ok", "ssd_mobilenet_v2": "ok"}}}
```

Readiness asks TF Serving whether each pinned model version is `AVAILABLE` and pings the configured count store (MongoDB or PostgreSQL). Failure causes are logged, not returned. The Compose `app` service uses it as its healthcheck, so `docker compose up --wait` returns once requests can succeed.

The two image endpoints take `threshold` (optional, `0`–`1`, default `0.5`, inclusive), `file` (JPEG or PNG) and `model_name` (optional, default: the manifest's `default_model`). Responses include the model that answered, e.g. `"model": {"name": "ssd_mobilenet_v2", "version": "1"}` (`version` is `null` in dev). All models add to the same running totals. Errors are returned as [RFC 7807](https://www.rfc-editor.org/rfc/rfc7807) `application/problem+json`:

| Status | When |
|---|---|
| `400` | Missing `file`, `threshold` not a number or outside `0`–`1`, unknown `model_name` (`errors` names the field and lists the models), or a file that isn't a JPEG/PNG image |
| `413` | Upload larger than `MAX_UPLOAD_BYTES` |
| `503` | TF Serving or the count database is unreachable |
| `500` | Unexpected error (details are logged, not returned) |

```json
{"type": "about:blank", "title": "Invalid request", "status": 400, "detail": "Request validation failed",
 "instance": "/object-count", "errors": [{"field": "threshold", "message": "must be between 0.0 and 1.0"}]}
```

> [!TIP]
> If you face service connectivity issues on Windows, try replacing "localhost" with "127.0.0.1" globally

## Configuration

Copy `.env.example` to `.env` to override defaults; `make` and `docker compose` both read it.

| Variable | Default | Used for |
|---|---|---|
| `ENV` | `dev` | `dev`: fake detectors + in-memory counts. `prod`: TF Serving + MongoDB |
| `HOST` | `127.0.0.1` | Dev server bind address (`0.0.0.0` to accept outside connections) |
| `PORT` | `5000` | Dev server port |
| `FLASK_DEBUG` | `0` | `1` enables the Flask debugger (never in production) |
| `MAX_UPLOAD_BYTES` | `10485760` (10 MB) | Larger uploads are rejected with `413` |
| `DEBUG_IMAGES` | `0` | `1` saves each image with its prediction boxes drawn to `tmp/debug/` |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. Logs go to stderr in one format: `time LEVEL [pid] logger: message` |
| `TFS_HOST` | `localhost` | TF Serving host |
| `TFS_PORT` | `8501` | TF Serving REST port |
| `MODELS_MANIFEST` | `models/models.json` | Which models exist, the default, their label maps and registry aliases |
| `MODELS_LOCK` | `tmp/model/models.lock.json` | Model versions pulled by `make pull-models`; `ENV=prod` calls exactly these and won't start without them |
| `MLFLOW_TRACKING_URI` | `sqlite:///tmp/mlflow/registry.db` | Model registry used by the `make *-models` targets; point it at a company MLflow server to use a private registry |
| `MLFLOW_ARTIFACTS_DIR` | `tmp/mlflow/artifacts` | Where a new local registry stores model files |
| `TFS_TIMEOUT` | `30` | Seconds to wait for a TF Serving response |
| `COUNT_REPO` | `memory` (dev), `mongo` (prod) | Count store: `memory`, `mongo` or `postgres` |
| `MONGO_HOST` | `localhost` | MongoDB host |
| `MONGO_PORT` | `27017` | MongoDB port |
| `MONGO_DB` | `prod_counter` | MongoDB database |
| `MONGO_TIMEOUT` | `5` | Seconds to wait for MongoDB before returning `503` |
| `POSTGRES_HOST` | `localhost` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `counter` | PostgreSQL database |
| `POSTGRES_USER` | `counter` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `counter` | PostgreSQL password (change outside local development) |
| `POSTGRES_TIMEOUT` | `5` | Seconds to wait for a PostgreSQL connection |
| `DATABASE_URL` | unset | Full PostgreSQL connection string; overrides the `POSTGRES_*` values |
| `TEST_POSTGRES_DSN`, `TEST_MONGO_HOST`, `TEST_MONGO_PORT` | unset | Integration tests use these servers instead of starting containers |

## Logs

The app logs to stderr, in one format for its own and library messages. The level comes from `LOG_LEVEL`. At `INFO` you get:

- one startup line per process with the models and versions served, `ENV`, the count store and whether debug images are on
- one line per TF Serving call: model, number of detections and time taken (`DEBUG` also logs the URL)
- an `ERROR` line for every `503` (detector or count store down, with the cause) and a traceback for every `500`

Request errors (`400`, `413`) aren't logged; the client gets the details. In Docker, gunicorn also writes one access line per request to stdout. See them with `make logs` or `docker compose logs app`.

## Development

| Command | Does |
|---|---|
| `make test` | Unit, API, contract and stub-TF-Serving integration tests: no Docker needed, ~6 s |
| `make coverage` | The same with a coverage report (fails under 90%) |
| `make test-integration` | Repo tests against real PostgreSQL and MongoDB, started with testcontainers (needs Docker, or set `TEST_POSTGRES_DSN` / `TEST_MONGO_HOST`) |
| `make test-models` | Model registry scripts against a temporary MLflow registry (needs `make setup-models`) |
| `make e2e` | Start the whole stack in Docker (app container, TF Serving with the real models, databases) and run the end-to-end tests; run `make models` first. `make test-e2e` runs the tests against a stack that's already up |
| `make docs` | Validate `docs/openapi.yaml` |
| `make lint` / `make format` | ruff check / apply fixes and formatting |
| `make typecheck` | mypy on `counter/` and `scripts/`: every function must be annotated (settings in `pyproject.toml`; tests are not type-checked) |
| `make security` | bandit and pip-audit |
| `make lock` | Regenerate `requirements.lock` / `requirements-dev.lock` after editing `requirements*.txt` (CI fails if they're out of date) |
| `make check` | lint + type check + spec validation + security + tests, the same as CI |

CI (`.github/workflows/ci.yml`) runs the test, integration, models, e2e, lint, security and docker jobs on every pull request. **How and why the project is tested at each level is explained in [`docs/TESTING.md`](docs/TESTING.md).**

Contract tests (`tests/entrypoints/test_openapi.py`) send a real request for every path and status code in `docs/openapi.yaml` and validate the response against it, and fail if a route and the spec disagree.

The same repo tests run against every `ObjectCountRepo` adapter (memory, MongoDB, PostgreSQL), so all of them behave the same way (`tests/adapters/test_count_repo_contract.py`).

Dependencies: `requirements*.txt` list the direct dependencies; `requirements.lock` and `requirements-dev.lock` (generated by `uv pip compile`) pin every transitive package too. `make setup`, CI and the Docker image install from the lock files, so every install gets the same versions. To add or bump a package, edit the `.txt` file, run `make lock`, and commit both.

## Windows without make

PowerShell equivalents of the main targets:

```powershell
uv venv --python 3.12 .venv
.venv\Scripts\Activate.ps1
uv pip install -r requirements-dev.lock

python -m pytest -m "not integration and not models"     # make test
python -m counter.entrypoints.webapp      # make run
docker compose up -d --wait               # make up
$env:ENV = "prod"; python -m counter.entrypoints.webapp   # make run-prod
```

Models (`make models`): run `python scripts/model_registry.py download`, then `publish` and `pull` with the Python from a venv that has `requirements-models.txt` installed.
