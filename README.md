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
                       make baseline        ──> tmp/baselines/<name>/<version>.json + stored with the version in MLflow
                       make evaluate        ──> precision/recall/F1 + model card stored with the version (quality gate)
```

| Model | Source | Role |
|---|---|---|
| `ssd_mobilenet_v2` (default) | SSD MobileNet v2 COCO, 2018-03-29 | The original model of this project |
| `acme_shelf_detector` | SSDLite MobileNet v2 COCO, 2018-05-09 (49 MB) | Simulated internal model: public weights published under an internal name. Its label map is a copy of COCO. |

- **Adding a model:** add an entry to `models/models.json` (name, serving type, registry alias, label map, source) and its label map under `models/labels/`, then `make models`. No code changes.
- **Releasing a new version (with the quality gate):**
  1. `make publish-models` registers it (say version 2); nothing is served yet.
  2. `make promote-model MODEL=acme_shelf_detector VERSION=2 ALIAS=candidate`, then `make pull-models` and restart TF Serving: it now loads the champion *and* the candidate; the app still calls only the champion.
  3. `make evaluate MODEL=acme_shelf_detector VERSION=2` (and the current champion, if it wasn't evaluated on the same set): precision, recall and F1 on a labelled evaluation set, stored as tags of the version together with a model card.
  4. Optionally, try it on real traffic first with a [shadow or canary release](#shadow-and-canary-releases).
  5. `make promote-model MODEL=acme_shelf_detector VERSION=2` moves `champion` to it, but refuses if the version wasn't evaluated or its F1 is more than 0.02 below the champion's on the same evaluation set. Then `make pull-models` and restart.
- **Rolling back:** `make promote-model MODEL=acme_shelf_detector VERSION=1 FORCE=1` skips the gate (recorded on the version as `promoted_without_gate`), then `make pull-models` and restart.
- **Evaluation set:** [`models/evaluation/coco_sample.json`](models/evaluation/coco_sample.json) labels which COCO classes are visible in each sample image (image-level, no boxes). Three images only demonstrate the gate; use `DATASET=` with a set of hundreds of images like the production traffic. Its fingerprint (labels + images) is stored with each evaluation, so versions are only compared on the same set.
- **Drift baseline for a version:** after `make up`, `make baseline` (optionally `IMAGES=/path/to/validation/images`); `make pull-models` fetches stored baselines with their versions. See [Model monitoring](#model-monitoring-drift).
- **Browsing the registry:** `make mlflow-ui`, then open http://127.0.0.1:5001.
- **Private registry:** set `MLFLOW_TRACKING_URI` to your MLflow server (with its credentials); the same commands work.

In dev (`ENV=dev`), every model in the manifest is served by the fake detector, so model selection works without Docker.

### Shadow and canary releases

An offline evaluation uses a fixed labelled set; a release on real traffic shows how a candidate version behaves on what clients actually send. Once a version is the `candidate` (step 2 above), `make pull-models` writes `tmp/model/candidates.lock.json` and TF Serving serves it next to the champion. `RELEASE_MODE` decides what the app does with it:

| `RELEASE_MODE` | The client gets | The candidate gets |
|---|---|---|
| `off` (default) | the champion's answer | nothing |
| `shadow` | the champion's answer, never slower or failing because of the candidate | a copy of each request in the background (`SHADOW_WORKERS` threads; beyond `SHADOW_MAX_PENDING` in flight a copy is dropped) |
| `canary` | the candidate's answer for `CANARY_PERCENT` % of requests (`model.version` in the response says which); if the candidate is unavailable, the champion answers | that share of the traffic |

```bash
RELEASE_MODE=shadow docker compose --profile app up -d app     # or canary with CANARY_PERCENT=10
make canary-check MODEL=acme_shelf_detector [WINDOW=1h]        # JSON verdict from Prometheus; exit 0 = promote
make canary-promote MODEL=acme_shelf_detector                  # the check, then promote the candidate (quality gate applies)
```

Either way the candidate's calls are recorded under its own version: latency and outcome metrics, the prediction log and drift (run `make baseline` once it's served). In shadow mode `shadow_class_agreement` measures how often both versions find the same classes. `GET /models` shows the running release, `model_release_info` tells Prometheus which version is the champion and which the candidate, and the `CandidateUnhealthy` alert fires when more than 5% of the candidate's calls fail. `make canary-check` compares the candidate with the champion over the window: it holds the release if the candidate saw fewer than 100 calls, its error rate is more than 1 point higher, its p95 latency more than 20% higher, or it drifted (PSI ≥ 0.25). The check is a command for a person or a cron job, not a loop inside the app: promoting still goes through the quality gate and `make pull-models`.

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
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. Logs go to stderr in one format: `time LEVEL [pid] [request_id] logger: message` |
| `LOG_FORMAT` | `text` | `json`: one JSON object per line (`time`, `level`, `logger`, `pid`, `request_id`, `message`, `exception`), for log shippers |
| `WEB_CONCURRENCY` | `2` | gunicorn workers in the Docker image |
| `PROMETHEUS_MULTIPROC_DIR` | `/tmp/prometheus` in Docker, unset otherwise | Shared directory where gunicorn workers write their metrics, so `/metrics` adds them up |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Grafana admin password (monitoring profile; viewers need no login) |
| `PREDICTION_LOG` | `memory` (dev), `postgres` (prod) | Where model outputs are logged for drift monitoring: `none`, `memory` or `postgres` (uses the `POSTGRES_*`/`DATABASE_URL` settings, whatever `COUNT_REPO` is) |
| `BASELINES_DIR` | `tmp/baselines` | Drift baselines, one `<model>/<version>.json` per version |
| `DRIFT_WINDOW_HOURS` | `24` | How much recent traffic is compared with the baseline |
| `DRIFT_MIN_IMAGES` | `30` | Below this many images in the window, no PSI is reported |
| `DRIFT_CACHE_SECONDS` | `300` | How long `/metrics` reuses a drift result |
| `RELEASE_MODE` | `off` | What the app does with each model's candidate version (prod): `off`, `shadow` or `canary` ([releases](#shadow-and-canary-releases)) |
| `CANARY_PERCENT` | `10` | Share of requests the candidate answers in a canary release (0–100) |
| `SHADOW_WORKERS` / `SHADOW_MAX_PENDING` | `2` / `4` | Background threads for shadow calls, and how many may be in flight before copies are dropped |
| `PROMETHEUS_URL` | `http://localhost:9090` | Prometheus queried by `make canary-check` |
| `TFS_HOST` | `localhost` | TF Serving host |
| `TFS_PORT` | `8501` | TF Serving REST port |
| `MODELS_MANIFEST` | `models/models.json` | Which models exist, the default, their label maps and registry aliases |
| `MODELS_LOCK` | `tmp/model/models.lock.json` | Model versions pulled by `make pull-models`; `ENV=prod` calls exactly these and won't start without them. The candidate versions are in `candidates.lock.json` next to it |
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

## Logs, metrics and dashboards

### Logs

The app logs to stderr, in one format for its own and library messages. The level comes from `LOG_LEVEL`, the format from `LOG_FORMAT` (`text` or `json`). Every line carries the request ID (`-` outside a request). At `INFO` you get:

- one startup line per process with the models and versions served, `ENV`, the count store and whether debug images are on
- one line per TF Serving call: model, number of detections and time taken (`DEBUG` also logs the URL)
- an `ERROR` line for every `503` (detector or count store down, with the cause) and a traceback for every `500`

Request errors (`400`, `413`) aren't logged; the client gets the details. In Docker, gunicorn also writes one access line per request to stdout, with its duration and request ID. See them with `make logs` or `docker compose logs app`.

### Request IDs

Every response has an `X-Request-ID` header. A caller's own ID is kept if it's at most 128 characters of letters, digits, `.`, `_` and `-`; otherwise the app generates one. Search the logs for it to follow one request.

### Metrics

`GET /metrics` serves Prometheus metrics (not part of the API contract, like `/docs`):

| Metric | Labels | Meaning |
|---|---|---|
| `http_requests_total` | `method`, `route`, `status` | Requests; `route` is the route pattern, `unmatched` for unknown URLs |
| `http_request_duration_seconds` | `method`, `route` | Request duration (histogram) |
| `detector_requests_total` | `model`, `version`, `outcome` | Detector calls: `ok`, `unavailable`, `invalid_image` or `error` |
| `detector_request_duration_seconds` | `model`, `version` | Detector call duration, TF Serving round trip included (histogram) |
| `objects_counted_total` | `object_class` | Objects added to the totals by `POST /object-count` |
| `model_drift_psi` | `model`, `version`, `feature` | Prediction drift against the version's baseline (see below) |
| `model_drift_window_images` | `model`, `version` | Images in the drift window |
| `prediction_log_dropped_total` | `reason` | Prediction records not stored (`queue_full`, `store_error`) |
| `model_release_info` | `model`, `version`, `role`, `mode` | 1 per served version: `role` champion or candidate, `mode` off, shadow or canary |
| `shadow_requests_total` | `model`, `version`, `outcome` | Shadow calls to a candidate: `compared`, `failed`, `dropped` |
| `shadow_class_agreement` | `model`, `version` | Overlap (Jaccard) of the classes found by the champion and the shadow candidate at a 0.5 score (histogram) |
| `canary_fallbacks_total` | `model`, `version` | Canary requests answered by the champion because the candidate was unavailable |

With several gunicorn workers, the Docker image sets `PROMETHEUS_MULTIPROC_DIR` so every scrape sees the whole server. TF Serving exposes its own metrics at `:8501/monitoring/prometheus/metrics`.

### Dashboards

```bash
make monitoring        # the whole stack plus Prometheus and Grafana
```

Grafana at [http://localhost:3000](http://localhost:3000) (dashboard "Object Counter": traffic, latency, server errors, detector calls and latency per model version, objects counted per class, prediction and input drift, champion vs candidate during a release); Prometheus at [http://localhost:9090](http://localhost:9090), with alert rules in [`monitoring/alerts.yml`](monitoring/alerts.yml) (`ModelDrift`, `InputDrift`, `HighServerErrorRate`, `DetectorUnavailable`, `CandidateUnhealthy`; routing them to e-mail or chat needs an Alertmanager). Configuration is in [`monitoring/`](monitoring/). `make e2e` starts the same profile and checks that Prometheus scrapes the app and TF Serving, loaded the alert rules, and that Grafana loaded the dashboard.

## Model monitoring (drift)

Metrics show whether the service works; drift monitoring shows whether the **model** still behaves as it did when it was released. It needs no labels.

1. **Prediction log.** Every successful model call is logged with its model, version, *every* raw score and class (including those below the caller's threshold: a model losing confidence shows up first as scores sliding toward the threshold), and statistics of the uploaded image: size, colour mode, brightness and contrast (computed on a reduced decode, so they cost little). `PREDICTION_LOG=postgres` (the prod default) writes to the table `prediction_logs` through a background thread, so a slow or unavailable database never delays or fails a request; dropped records are counted in `prediction_log_dropped_total`. `memory` is the dev default; `none` turns it off.
2. **Baseline per version.** `make baseline` runs reference images through each served version and stores the distributions with that version in MLflow (and in `tmp/baselines/`); `make pull-models` brings them along with the model. The three sample images only demonstrate the workflow: use `IMAGES=` with a validation set that looks like production traffic.
3. **Comparison.** For each served version, the last `DRIFT_WINDOW_HOURS` of traffic is compared with its baseline using the Population Stability Index (PSI). Below 0.1 is stable, 0.1–0.25 a moderate change, 0.25 or more drift. Results appear as `model_drift_psi{feature=…}` on `/metrics` (recomputed at most every `DRIFT_CACHE_SECONDS`), in the Grafana dashboard and in two alerts:

| Kind | Features | Catches | Alert |
|---|---|---|---|
| Prediction drift | `scores`, `detections` (per image), `classes` (both at a 0.5 score) | the model's outputs changed | `ModelDrift` (warning) |
| Input drift | `aspect_ratio`, `megapixels`, `brightness`, `contrast`, `color_mode` | the uploaded images changed: a new camera, compression, client or lighting, often before the outputs change | `InputDrift` (info) |

Baselines computed before input statistics existed report `no_reference` for the input features; run `make baseline` again.

```bash
make drift             # JSON report per served version; python -m counter.entrypoints.drift --fail-on-drift exits 1 on drift (for cron)
```

Drift doesn't say the model is *wrong*, only that its outputs changed: new cameras, lighting, a different mix of scenes, or a broken upstream component. Checking accuracy needs labels (plan item X7).

## Development

| Command | Does |
|---|---|
| `make test` | Unit, API, contract and stub-TF-Serving integration tests: no Docker needed, ~6 s |
| `make coverage` | The same with a coverage report (fails under 90%) |
| `make test-integration` | Repo tests against real PostgreSQL and MongoDB, started with testcontainers (needs Docker, or set `TEST_POSTGRES_DSN` / `TEST_MONGO_HOST`) |
| `make test-models` | Model registry scripts against a temporary MLflow registry (needs `make setup-models`) |
| `make e2e` | Start the whole stack in Docker (app container, TF Serving with the real models, databases, Prometheus and Grafana) and run the end-to-end tests; run `make models` first. `make test-e2e` runs the tests against a stack that's already up |
| `make baseline` / `make drift` / `make evaluate` | Drift baselines for the served versions (needs `make up` and `make setup-models`) / drift report / quality-gate evaluation of a served version (`MODEL=`, `VERSION=`) |
| `make canary-check` / `make canary-promote` | Compare a released candidate with the champion in Prometheus (`MODEL=`, `WINDOW=`) / the check, then promote the candidate |
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
