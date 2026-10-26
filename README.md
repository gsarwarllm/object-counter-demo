# NIQ Innovation Enablement - Object Counter Challenge

The goal of this repo is demonstrate how to apply Hexagonal Architecture in a ML based system.

This application consists in a Flask API that receives an image and a threshold and returns the number of objects detected in the image.

The application is composed of three layers:

- **entrypoints**: Exposes the API and receives the requests. It is also responsible for validating the requests and returning the responses.

- **adapters**: Communicates with external services. It is responsible for translating the domain objects to the external services objects and vice-versa.

- **domain**: Business logic. It is responsible for orchestrating the calls to the external services and for applying the business rules.

The model used in this example has been taken from
[Kaggle](https://www.kaggle.com/models/google/mobilenet-v2/tensorFlow1/openimages-v4-ssd-mobilenet-v2/1)

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

## Run with the real model (Docker)

```bash
make download-model   # SSD MobileNet v2 into tmp/model (skips if already there)
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

## Call the service

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

Both endpoints take `threshold` (optional, `0`–`1`, default `0.5`, inclusive) and `file` (JPEG or PNG). Errors are returned as [RFC 7807](https://www.rfc-editor.org/rfc/rfc7807) `application/problem+json`:

| Status | When |
|---|---|
| `400` | Missing `file`, `threshold` not a number or outside `0`–`1` (`errors` names the field), or a file that isn't a JPEG/PNG image |
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
| `ENV` | `dev` | `dev`: fake detector + in-memory counts. `prod`: TF Serving + MongoDB |
| `HOST` | `127.0.0.1` | Dev server bind address (`0.0.0.0` to accept outside connections) |
| `PORT` | `5000` | Dev server port |
| `FLASK_DEBUG` | `0` | `1` enables the Flask debugger (never in production) |
| `MAX_UPLOAD_BYTES` | `10485760` (10 MB) | Larger uploads are rejected with `413` |
| `DEBUG_IMAGES` | `0` | `1` saves each image with its prediction boxes drawn to `tmp/debug/` |
| `TFS_HOST` | `localhost` | TF Serving host |
| `TFS_PORT` | `8501` | TF Serving REST port |
| `MODEL_NAME` | `ssd_mobilenet_v2` | Model name in TF Serving |
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

## Development

| Command | Does |
|---|---|
| `make test` | Unit and API tests, no Docker needed |
| `make test-integration` | Repo tests against real PostgreSQL and MongoDB, started with testcontainers (needs Docker, or set `TEST_POSTGRES_DSN` / `TEST_MONGO_HOST`) |
| `make lint` / `make format` | ruff check / apply fixes and formatting |
| `make security` | bandit and pip-audit |
| `make check` | lint + security + tests, the same as CI |

CI (`.github/workflows/ci.yml`) runs the test, integration, lint, security and docker jobs on every pull request.

The same repo tests run against every `ObjectCountRepo` adapter (memory, MongoDB, PostgreSQL), so all of them behave the same way (`tests/adapters/test_count_repo_contract.py`).

## Windows without make

PowerShell equivalents of the main targets:

```powershell
uv venv --python 3.12 .venv
.venv\Scripts\Activate.ps1
uv pip install -r requirements-dev.txt

python -m pytest -m "not integration"     # make test
python -m counter.entrypoints.webapp      # make run
docker compose up -d --wait               # make up
$env:ENV = "prod"; python -m counter.entrypoints.webapp   # make run-prod
```

Download the model by following the steps in `scripts/download_model.sh`, or run it from Git Bash or WSL.
