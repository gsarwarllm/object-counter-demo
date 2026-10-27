# Plan: Object Counter Assignment

This is the working plan for the assignment in `Task.md`. It is based on a review of the
current code (`counter/`, `tests/`, `README.md`, `requirements.txt`, `.vscode/launch.json`,
`tmp/model/model_config.config`).

**Contents**

1. [Current state and how to run](#1-current-state-and-how-to-run)
2. [Scope: mandatory vs optional](#2-scope-mandatory-vs-optional)
3. [Missing requirements and ambiguities](#3-missing-requirements-and-ambiguities)
4. [Priorities and milestones](#4-priorities-and-milestones)
5. [API specification (contract for every API)](#5-api-specification-contract-for-every-api)
6. [Mandatory tasks (Task.md 1–6 + setup)](#6-mandatory-tasks)
7. [Optional enhancements](#7-optional-enhancements)
8. [Optional: Flask → FastAPI migration](#8-optional-flask--fastapi-migration)
9. [Optional: equivalent implementation in Spring Boot](#9-optional-equivalent-implementation-in-spring-boot)
10. [Repository strategy: Flask, FastAPI and Spring Boot](#10-repository-strategy-flask-fastapi-and-spring-boot)
11. [Appendix A: OpenAPI 3 contract (`docs/openapi.yaml`)](#appendix-a-openapi-3-contract-docsopenapiyaml)
12. [Appendix B: Definition of done (whole assignment)](#appendix-b-definition-of-done-whole-assignment)

---

## 1. Current state and how to run

### Environment on this machine

| Item | State | Consequence |
|---|---|---|
| System Python | 3.14, no `pip`/`ensurepip` | `numpy==1.26.4` can't be installed on it |
| `uv` | installed in `~/.local/bin` | provides a Python 3.12 venv at `.venv` |
| Docker | **not installed**, `sudo` needs a password | prod mode (TF Serving + MongoDB) can't run yet |
| Dev mode | works | 5/5 tests pass, `curl` works on port 5000 |

### Run in dev mode (fake detector + in-memory store)

```bash
# One-time setup
curl -LsSf https://astral.sh/uv/install.sh | sh
cd /home/gssarwar/project/object-counter-vibe-coding
~/.local/bin/uv venv --python 3.12 .venv
~/.local/bin/uv pip install --python .venv/bin/python -r requirements.txt

# Run (keep this terminal open)
source .venv/bin/activate
export PYTHONPATH=.
python -m counter.entrypoints.webapp            # http://localhost:5000

# Call it (second terminal)
curl -F "threshold=0.9" -F "file=@resources/images/boy.jpg" http://localhost:5000/object-count

# Tests
pytest                                          # 5 passed
```

In dev mode every image returns one "cat": `FakeObjectDetector` ignores the image.

To enable prod mode, install Docker:
`sudo apt install -y docker.io && sudo usermod -aG docker $USER`, log out and back in, then
follow `README.md`.

### Architecture today (hexagonal)

```
entrypoints/webapp.py (Flask)  ─┐
entrypoints/main.py   (CLI)    ─┼─> config.get_count_action()  (ENV=dev|prod)
                                │
                                ▼
                  domain/actions.py  CountDetectedObjects
                     │  uses ports (domain/ports.py)
          ┌──────────┴───────────┐
   ObjectDetector           ObjectCountRepo
   ├ TFSObjectDetector      ├ CountMongoDBRepo
   └ FakeObjectDetector     └ CountInMemoryRepo
```

### Behaviour of the existing API that matters for the plan

| Input | Current behaviour | Desired |
|---|---|---|
| Valid image, `threshold=0.9` | 200 JSON | unchanged |
| `threshold` missing | default `0.5` | keep, and document it |
| `threshold=abc` | `ValueError` → **500** HTML page | 400 JSON error |
| `threshold=5` or `-1` | accepted silently, 200 | 400 JSON error |
| `file` missing | Flask `BadRequestKeyError` → **400 HTML** page | 400 JSON error |
| Non-image file (e.g. `.txt`) | Pillow `UnidentifiedImageError` → **500** | 400 JSON error |
| PNG with alpha / greyscale (prod) | `reshape((h, w, 3))` fails → **500** | converted to RGB, 200 |
| Very large upload | no limit | 413 JSON error |
| TF Serving or Mongo down | exception → **500** | 503 JSON error |

---

## 2. Scope: mandatory vs optional

**Pass bar from `Task.md`:** at least 3 exercises solved correctly. The evaluation also scores
clean code, **automated reproducible setup** (README, Makefile preferred over many commands)
and documentation quality. This plan aims to deliver **all six** tasks.

### Mandatory (from `Task.md` and its evaluation criteria)

| ID | Task | Source |
|---|---|---|
| M1 | Endpoint that returns the list of predictions | Task.md #1 |
| M2 | Relational DB adapter for `ObjectCountRepo` (PostgreSQL) | Task.md #2 |
| M3 | Code review: proposed improvements | Task.md #3 |
| M4 | Implement at least one improvement | Task.md #4 |
| M5 | Setup changes for multiple internal (private) models | Task.md #5 |
| M6 | Option **(a)** integration + e2e tests; outline option (b) | Task.md #6 |
| M7 | Automated, reproducible setup: `Makefile`, `docker-compose.yml`, `README.md` | Task.md "Evaluation" |
| M8 | API documentation: OpenAPI/Swagger for every endpoint, request/response schemas, validation, error format | Task.md "Evaluation: additional documentation", requested for this plan |

M7 and M8 are implemented as part of M4, since they are the improvements with the highest value.

### Optional (only if time permits)

| ID | Enhancement |
|---|---|
| O1 | Authentication and authorization (API key, then JWT/OAuth2) |
| O2 | Extra endpoints: `GET /health`, `GET /object-counts` (read totals) |
| O3 | CI pipeline (GitHub Actions): lint, unit, integration tests |
| O4 | Observability: structured logging, request IDs, Prometheus metrics |
| O5 | Rate limiting |
| O6 | Flask → FastAPI migration (section 8) |
| O7 | Equivalent Spring Boot implementation (section 9) |
| O8 | Implement option 6(b), multi-framework detectors, beyond the outline |

---

## 3. Missing requirements and ambiguities

Each item lists the **decision taken** in this plan, so the work isn't blocked. Confirm
these before or during the interview.

| # | Topic | Ambiguity / gap | Decision (assumption) |
|---|---|---|---|
| A1 | Predictions endpoint path | Not specified | `POST /object-predictions`; keep `POST /object-count` unchanged |
| A2 | Predictions response shape | "return the list of predictions": a bare array or an object? | JSON object `{ "threshold": 0.5, "count": N, "predictions": [...] }`. It can be extended without breaking clients. |
| A3 | Predictions side effects | Should it update the stored counts? | **No**: read-only; it never calls the repo |
| A4 | Threshold semantics | Inclusive or exclusive? Range? Default? | Inclusive (`score >= threshold`, as in `over_threshold`); range `[0.0, 1.0]`; default `0.5` (current behaviour) |
| A5 | Prediction order | Not specified | Sorted by `score` descending |
| A6 | Count order | `current_objects` follows dict insertion order (not deterministic for clients) | Sort by `count` desc, then `object_class` asc |
| A7 | Box format | Not documented; TF returns `[ymin, xmin, ymax, xmax]` | Response uses `xmin, ymin, xmax, ymax`, **normalised 0–1** relative to image size |
| A8 | Which RDBMS | "MySQL or PostgreSQL" | **PostgreSQL 16**; the SQL avoids Postgres-only features except the upsert (MySQL equivalent documented) |
| A9 | Choosing the repo | `ENV=prod` hard-codes Mongo | New variable `COUNT_REPO=memory\|mongo\|postgres`; keep Mongo |
| A10 | Schema management | Not specified | `CREATE TABLE IF NOT EXISTS` on start-up, plus `docs/sql/001_object_counts.sql`; Alembic/Flyway is optional |
| A11 | `total_objects` meaning | Global? Per model? Per user? Resettable? | Global all-time totals across all requests; no reset endpoint (optional admin endpoint under O1) |
| A12 | Concurrency | update-then-read isn't atomic | Each update is atomic per class (upsert / `$inc`); totals may include concurrent requests. Accepted and documented. |
| A13 | Image constraints | Formats, size, colour modes | JPEG and PNG; max **10 MB**; converted to RGB; anything else → 400 |
| A14 | Error format | Not defined | **RFC 7807 Problem Details** (`application/problem+json`) in all three frameworks |
| A15 | Error codes | Not defined | 400 validation/invalid image, 401/403 (only with O1), 413 too large, 500 unexpected, 503 detector/DB unavailable |
| A16 | API versioning | None | Keep current paths (backwards compatible). A `/v1` prefix is optional later. |
| A17 | Task 3/5/6b deliverable | Code or text? Where? | Written answers in `docs/ANSWERS.md`, linked from `README.md` |
| A18 | Task 6 choice | (a) or (b) | Implement (a); outline (b) in `docs/ANSWERS.md` |
| A19 | `model_name` field | Sent by `test_webapp.py`, ignored by the app | Optional, validated field since M5: one of the models in `models/models.json` (listed by `GET /models`), default = the manifest's `default_model` |
| A20 | Windows support | README has PowerShell commands; a Makefile is Unix-only | Makefile + docker compose for Unix/WSL; keep the PowerShell notes in the README |
| A21 | Debug images | Written to the CWD on every request unless `python -O` | Off by default; `DEBUG_IMAGES=true` writes to `tmp/debug/` |
| A22 | Python version | README says ">= 3.10"; 3.14 fails | Pin **3.12** (`.python-version`, `pyproject.toml`) |
| A23 | Authentication | Not mentioned at all | Out of mandatory scope; optional O1 |
| A24 | Non-functional | No latency, throughput or availability targets | No targets; document the TF Serving timeout (10 s) and the upload limit |
| A25 | Where the Spring Boot version lives | Same repo, a branch, or a separate repo? | **Same repository**, in a `spring-boot/` directory; Python stays at the root. Not a branch. See section 10. |

---

## 4. Priorities and milestones

| Priority | Meaning |
|---|---|
| **P0** | Must have: needed to pass and to run the project |
| **P1** | Should have: completes the assignment to a high standard |
| **P2** | Nice to have: optional, only if time permits |

| Order | ID | Item | Priority | Size | Depends on |
|---|---|---|---|---|---|
| 1 | M7 | Makefile, docker-compose, Dockerfile, pinned Python, `pyproject.toml` | P0 | M | none |
| 2 | M4 | Validation + RFC 7807 errors, resource paths, debug flag, Mongo client reuse, TFS timeout/logging | P0 | M | M7 |
| 3 | M1 | `POST /object-predictions` | P0 | S | M4 (validation helpers) |
| 4 | M2 | `CountPostgresRepo` + `COUNT_REPO` switch | P0 | M | M7 (postgres service) |
| 5 | M8 | `docs/openapi.yaml` + Swagger UI at `/docs` | P1 | S | M1 |
| 6 | M6a | Integration + e2e tests, pytest markers | P1 | M | M2, M7 |
| 7 | M3, M5, M6b | Written answers in `docs/ANSWERS.md` | P1 | S | none |
| 8 | O2, O3 | Health/totals endpoints, CI | P2 | S | M7 |
| 9 | O1 | Auth (API key) | P2 | S | M8 |
| 10 | O6 | FastAPI migration | P2 | M | M1, M4, M8 |
| 11 | O7 | Spring Boot implementation | P2 | L | M8 (the contract) |

Size: S ≈ under half a day, M ≈ a day, L ≈ several days.

---

## 5. API specification (contract for every API)

The contract is **framework independent**. Flask, FastAPI and Spring Boot must all produce the
same JSON. The source of truth is `docs/openapi.yaml` (Appendix A).

### 5.1 Common conventions

| Item | Value |
|---|---|
| Base URL (dev) | `http://localhost:5000` (Flask), `:8000` (FastAPI), `:8080` (Spring Boot) |
| Request content type | `multipart/form-data` for image endpoints |
| Response content type | `application/json`; errors use `application/problem+json` |
| Field naming | `snake_case` (matches the existing API; Spring needs the Jackson `SNAKE_CASE` naming strategy) |
| Number format | `score` and box values are floats in `[0, 1]`; counts are integers `>= 0` |
| Max upload size | 10 MB (`MAX_UPLOAD_BYTES`, configurable) |
| Accepted images | JPEG, PNG; decoded by Pillow, converted to RGB |
| Docs | Swagger UI at `/docs`, raw spec at `/openapi.json` (or `/openapi.yaml` for Flask) |

### 5.2 Shared schemas (DTOs)

| Schema | Fields | Validation / notes |
|---|---|---|
| `Box` | `xmin`, `ymin`, `xmax`, `ymax`: number | each in `[0, 1]`; `xmin <= xmax`, `ymin <= ymax` |
| `Prediction` | `class_name`: string, `score`: number, `box`: `Box` | `score` in `[0, 1]` |
| `ObjectCount` | `object_class`: string, `count`: integer | `count >= 0` |
| `Model` | `name`: string, `version`: string or null | the model that answered; `version` is the pulled registry version (`null` in dev, where fakes answer) |
| `CountResponse` | `current_objects`: `ObjectCount[]`, `total_objects`: `ObjectCount[]`, `model`: `Model` | arrays may be empty; sorted per A6 |
| `PredictionsResponse` | `threshold`: number, `count`: integer, `predictions`: `Prediction[]`, `model`: `Model` | `count == len(predictions)`; sorted per A5 |
| `ModelsResponse` | `default_model`: string, `models`: `Model[]` | models sorted by name |
| `Problem` (error) | `type`: uri, `title`: string, `status`: integer, `detail`: string, `instance`: string, `errors`: `FieldError[]` (optional) | RFC 7807 |
| `FieldError` | `field`: string, `message`: string | one entry per invalid field |

Request DTO (the same for both image endpoints):

| Field | In | Type | Required | Default | Validation | Error when invalid |
|---|---|---|---|---|---|---|
| `file` | form part | binary | yes | n/a | present, non-empty, ≤ 10 MB, decodable as JPEG/PNG | 400 (`missing`/`invalid image`), 413 (too large) |
| `threshold` | form field | number | no | `0.5` | parses as float, `0.0 <= t <= 1.0` | 400 |
| `model_name` | form field | string | no | the manifest's `default_model` | one of the models in `models/models.json` (see `GET /models`); empty = default | 400 (`unknown model`, lists the available models) |

Domain mapping (the domain stays free of HTTP and framework types):

| HTTP DTO | Domain object (`counter/domain/models.py`) |
|---|---|
| `CountRequest(image: BytesIO, threshold: float)` | arguments of `CountDetectedObjects.execute` |
| `PredictionsRequest(image: BytesIO, threshold: float)` | arguments of `DetectObjects.execute` (new) |
| `CountResponse` JSON | `CountResponse` dataclass |
| `PredictionsResponse` JSON | `List[Prediction]` + threshold, built in the entrypoint |

### 5.3 Error handling

New `counter/domain/errors.py`. Adapters raise domain errors; only the entrypoint knows about
HTTP.

| Error (raised by) | HTTP | `title` |
|---|---|---|
| `ValidationError` (entrypoint parsing) | 400 | `Invalid request` |
| `InvalidImageError` (image decoding in adapter or entrypoint) | 400 | `Invalid image` |
| Upload over the limit (framework) | 413 | `Payload too large` |
| `DetectorUnavailableError` (`TFSObjectDetector`: timeout, connection error, 5xx) | 503 | `Object detector unavailable` |
| `RepositoryUnavailableError` (Mongo/Postgres connection error) | 503 | `Count repository unavailable` |
| Unauthenticated / forbidden (only with O1) | 401 / 403 | `Unauthorized` / `Forbidden` |
| Anything else | 500 | `Internal server error` (no stack trace in the body; logged server-side) |

Example error body:

```json
{
  "type": "about:blank",
  "title": "Invalid request",
  "status": 400,
  "detail": "Request validation failed",
  "instance": "/object-count",
  "errors": [{ "field": "threshold", "message": "must be between 0.0 and 1.0" }]
}
```

### 5.4 `POST /object-count` (exists: counts objects and updates totals)

**Purpose:** detect objects, count those with `score >= threshold` by class, add these counts
to the stored totals, and return both.

**Request**

```bash
curl -F "threshold=0.9" -F "file=@resources/images/boy.jpg" http://localhost:5000/object-count
```

**Response 200** (`CountResponse`)

```json
{
  "current_objects": [ { "object_class": "person", "count": 1 } ],
  "total_objects":   [ { "object_class": "cat", "count": 3 }, { "object_class": "person", "count": 1 } ],
  "model": { "name": "ssd_mobilenet_v2", "version": "1" }
}
```

**Status codes:** 200, 400, 413, 500, 503 (401/403 with O1).

**Data flow**

```
Client ─ multipart(file, threshold) ─> webapp route /object-count
  1. parse_count_request(request)          -> CountRequest | ValidationError(400)
  2. CountDetectedObjects.execute(image, threshold)
       a. ObjectDetector.predict(image)    -> List[Prediction]   (TFS / Fake)
       b. over_threshold(predictions, t)   -> List[Prediction]
       c. count(valid)                     -> List[ObjectCount]
       d. ObjectCountRepo.update_values()  (atomic per class)    (Mongo / Postgres / memory)
       e. ObjectCountRepo.read_values()    -> List[ObjectCount]
       -> CountResponse
  3. to_count_response_dto(CountResponse)   -> dict (sorted per A6)
  4. 200 application/json
Errors at any step -> error handler -> application/problem+json (table 5.3)
```

**Side effects:** writes to the count repository. It is **not idempotent**: sending the same
image twice adds to the totals twice.

### 5.5 `POST /object-predictions` (new, M1: returns predictions)

**Purpose:** detect objects and return every prediction with `score >= threshold`. Read-only.

**Request**

```bash
curl -F "threshold=0.5" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-predictions
```

**Response 200** (`PredictionsResponse`)

```json
{
  "threshold": 0.5,
  "count": 1,
  "predictions": [
    {
      "class_name": "cat",
      "score": 0.9991,
      "box": { "xmin": 0.3673, "ymin": 0.2783, "xmax": 0.7358, "ymax": 0.6989 }
    }
  ],
  "model": { "name": "ssd_mobilenet_v2", "version": "1" }
}
```

**Status codes:** 200, 400, 413, 500, 503 (401/403 with O1).

**Data flow**

```
Client ─ multipart(file, threshold) ─> webapp route /object-predictions
  1. parse_predictions_request(request)     -> PredictionsRequest | ValidationError(400)
  2. DetectObjects.execute(image, threshold)
       a. ObjectDetector.predict(image)     -> List[Prediction]
       b. over_threshold(...) + sort by score desc
       -> List[Prediction]                  (no repository call)
  3. to_predictions_response_dto(threshold, predictions)
  4. 200 application/json
```

**Side effects:** none. Idempotent and safe to retry.

### 5.5a `GET /models` (M5: lists the served models)

**Purpose:** tell clients which values `model_name` accepts and which model answers by default.

```bash
curl http://localhost:5000/models
```

**Response 200** (`ModelsResponse`)

```json
{
  "default_model": "ssd_mobilenet_v2",
  "models": [
    { "name": "acme_shelf_detector", "version": "1" },
    { "name": "ssd_mobilenet_v2", "version": "1" }
  ]
}
```

**Status codes:** 200. **Side effects:** none.

### 5.6 Optional endpoints (O2)

| Method + path | Purpose | Response | Codes |
|---|---|---|---|
| `GET /health` | liveness: the process is up | `{ "status": "ok" }` | 200 |
| `GET /health/ready` | readiness: every model's pinned version `AVAILABLE` in TF Serving and the repo reachable | `{ "status": "ok", "checks": { "repository": "ok", "detectors": { "<model>": "ok" } } }` (one entry per model, since M5) | 200, 503 |
| `GET /object-counts?object_class=cat&object_class=dog` | read totals without uploading (uses the existing `read_values(object_classes)`), sorted by class | `{ "total_objects": ObjectCount[] }` | 200, 400 (empty `object_class`), 503 |

### 5.7 How the OpenAPI docs are produced in each framework

| Framework | Approach | Where |
|---|---|---|
| Flask (now) | **Contract first:** hand-written `docs/openapi.yaml` (Appendix A), served by Flask at `/openapi.yaml`, with Swagger UI at `/docs` via `flask-swagger-ui` | `counter/entrypoints/webapp.py`, `docs/openapi.yaml` |
| FastAPI (O6) | Generated from Pydantic models + `responses=` / `openapi_examples`; compared against `docs/openapi.yaml` in a test | `/docs`, `/redoc`, `/openapi.json` |
| Spring Boot (O7) | `springdoc-openapi-starter-webmvc-ui` + `@Operation`, `@ApiResponse`, `@Schema` | `/swagger-ui.html`, `/v3/api-docs` |

**Contract tests (P1):** `openapi-spec-validator` checks the YAML file is valid. Optionally,
`schemathesis run docs/openapi.yaml --base-url http://localhost:5000` fuzzes the API
against the spec.

**Acceptance criteria (M8)**
- [ ] `docs/openapi.yaml` is valid OpenAPI 3.0 (validated in a test).
- [ ] Every endpoint documents its request schema, response schema, **every** status code from the tables above, and at least one example per status code.
- [ ] `/docs` shows Swagger UI, and "Try it out" works for both image endpoints in dev mode.
- [ ] Real responses match the documented schemas (API tests assert the JSON shape).
- [ ] The README links to `/docs` and `docs/openapi.yaml`.

---

## 6. Mandatory tasks

### M7: Automated, reproducible setup (P0)

**Goal:** a new developer runs the project with 1–2 commands, as the evaluation asks.

**Code changes**

| File | Change |
|---|---|
| `Makefile` (new) | targets below |
| `docker-compose.yml` (new) | services `tfserving`, `mongo`, `postgres`, `app`; healthchecks; volumes for the model |
| `Dockerfile` (new) | `python:3.12-slim`, install deps, run with `gunicorn` |
| `pyproject.toml` (new) | project metadata, `requires-python = ">=3.12,<3.13"`, pytest config (`pythonpath = ["."]`, markers) |
| `.python-version` (new) | `3.12` |
| `requirements.txt` → `requirements.txt` + `requirements-dev.txt` | runtime vs dev/test deps |
| `scripts/download_model.sh` (new) | the README model steps; idempotent (skips if already present) |
| `.env.example` (new) | every env var with its default |
| `tmp/model/model_config.config` | fix: reference `ssd_mobilenet_v2`, not `rfcn` |
| `README.md` | rewrite setup around `make` targets; keep the PowerShell notes |

**Makefile targets**

| Target | Does |
|---|---|
| `make setup` | create `.venv` with uv/Python 3.12, install runtime + dev deps |
| `make run` | dev server (fakes) on :5000 |
| `make download-model` | `scripts/download_model.sh` |
| `make up` / `make down` | `docker compose up -d` / `down` (tfserving, mongo, postgres) |
| `make run-prod` | `ENV=prod` server against compose services |
| `make test` | unit + API tests (no Docker needed) |
| `make test-integration` | tests marked `integration` (needs Docker) |
| `make test-e2e` | full stack in compose + e2e tests |
| `make lint` | `ruff check` + `ruff format --check` |
| `make docs` | validate `docs/openapi.yaml` |

**Steps**
1. Add `pyproject.toml`, `.python-version` and `requirements-dev.txt` (`pytest`, `ruff`, `testcontainers`, `responses`, `openapi-spec-validator`).
2. Move the README model download into `scripts/download_model.sh`.
3. Write `docker-compose.yml` with healthchecks, and a `Dockerfile` for the app.
4. Write the `Makefile`.
5. Rewrite the README "Setup" and "Run" sections to use `make`.

**Acceptance criteria**
- [ ] On a clean clone: `make setup && make test` passes without Docker.
- [ ] `make download-model && make up && make run-prod` gives real detections for `resources/images/cat.jpg`.
- [ ] `PYTHONPATH` no longer needs to be exported manually.
- [ ] Every env var is listed in `.env.example` and the README.

### M4: Implement improvements (P0)

Proposed in M3; these are the ones to implement.

| # | Improvement | Files | Steps |
|---|---|---|---|
| I1 | Request validation + RFC 7807 errors | `counter/entrypoints/schemas.py` (new), `counter/entrypoints/errors.py` (new), `counter/domain/errors.py` (new), `webapp.py` | parse/validate `file` and `threshold` in one function; register error handlers per table 5.3; set `MAX_CONTENT_LENGTH` |
| I2 | Robust image decoding | `counter/adapters/object_detector.py` | `Image.open(...).convert("RGB")`, `np.asarray(...)`, raise `InvalidImageError` on `UnidentifiedImageError` |
| I3 | TF Serving client hardening | `object_detector.py` | `requests.post(url, json=..., timeout=10)`, `raise_for_status()`, wrap errors in `DetectorUnavailableError`, `logging` instead of `print` |
| I4 | Reuse `MongoClient` | `counter/adapters/count_repo.py` | create the client once in `__init__`; set `serverSelectionTimeoutMS`; wrap `PyMongoError` |
| I5 | Debug images behind a flag | `counter/domain/actions.py`, `counter/config.py`, `counter/debug.py` | inject a `debug_image_writer` (or `None`) instead of using `__debug__`; output to `tmp/debug/` |
| I6 | Location-independent resource paths | `object_detector.py`, `debug.py` | `Path(__file__).resolve().parent / ...` |
| I7 | Explicit config | `counter/config.py` | dict registry instead of `globals()`; clear error for unknown `ENV`; cast ports to `int`; add `COUNT_REPO` |
| I8 | In-memory repo fix | `count_repo.py` | `read_values([...])` skips unknown classes instead of returning `None` |
| I9 | Production server | `Dockerfile`, `Makefile` | `gunicorn "counter.entrypoints.webapp:create_app()"`; `debug=True` only in dev |

**Acceptance criteria**
- [ ] Every row in the "existing behaviour" table in section 1 behaves as in the "Desired" column, with a test for each.
- [ ] No `print` calls remain in `counter/`.
- [ ] The app starts and works from any working directory.
- [ ] With `DEBUG_IMAGES` unset, no files are written per request.

### M1: Endpoint that returns the list of predictions (P0)

**Goal:** `POST /object-predictions` per section 5.5.

**Why POST, although the endpoint is read-only**
- The request carries an image. A GET body has no defined semantics (RFC 9110), and proxies, CDNs and clients such as `fetch` may drop it or reject it.
- A base64 image doesn't fit in a URL (limits are about 2–8 KB) and would end up in access logs.
- `multipart/form-data` uploads use POST, the same as `/object-count`, so both endpoints share one input format.
- Trade-off: POST doesn't signal that the endpoint is safe, so responses aren't cached or retried automatically. The OpenAPI spec and section 5.5 document that it is side-effect free and idempotent.
- Alternatives rejected: `GET ?image_url=` (server-side fetch is an SSRF risk and adds latency), the HTTP `QUERY` method (draft, not widely supported), `PUT` (wrong meaning: it stores a resource).
- Precedent: TF Serving's `:predict` endpoint, which this app calls, is also POST.

**Code changes**

| File | Change |
|---|---|
| `counter/domain/actions.py` | new `DetectObjects(object_detector)` with `execute(image, threshold) -> List[Prediction]`; extract the shared "predict + filter" into a function used by both actions |
| `counter/domain/predictions.py` | add `sort_by_score(predictions)` (pure) |
| `counter/config.py` | `get_detect_action()`; build the detector in one place shared by both actions |
| `counter/entrypoints/schemas.py` | `parse_predictions_request`, `to_predictions_response_dto` |
| `counter/entrypoints/webapp.py` | new route |
| `docs/openapi.yaml` | document the endpoint (Appendix A) |
| `tests/domain/test_actions.py` | unit tests for `DetectObjects` |
| `tests/entrypoints/test_webapp.py` | API tests: 200 shape, 400 cases, no repo writes |
| `README.md` | curl example |

**Implementation steps** (each step is one commit and leaves `pytest` green; branch `feat/m1-predictions-endpoint`)

| # | Step | Files | Tests | Done when |
|---|---|---|---|---|
| M1.1 | Add pure `sort_by_score(predictions)` (score descending, stable) | `counter/domain/predictions.py` | `tests/domain/test_predictions.py`: sorted order, ties keep input order, empty list | unit tests pass |
| M1.2 | Extract shared `detect_over_threshold(detector, image, threshold)` and have `CountDetectedObjects` use it (no behaviour change) | `counter/domain/actions.py` | existing `test_actions.py` passes unchanged | refactor only, same outputs |
| M1.3 | Add `DetectObjects(object_detector)` with `execute(image, threshold) -> List[Prediction]` (filter + sort, no repo) | `counter/domain/actions.py` | `test_actions.py`: filtering, inclusive `>=`, sorting, empty result, no repo dependency | unit tests pass (write them first) |
| M1.4 | Wire it in the composition root: build the detector once, add `get_detect_action()` | `counter/config.py` | `pytest` still green | both actions share one detector instance |
| M1.5 | Add request/response helpers: `parse_predictions_request`, `to_predictions_response_dto` (`{threshold, count, predictions[]}`) | `counter/entrypoints/schemas.py` (new) | unit tests for parsing and DTO shape | helpers tested in isolation |
| M1.6 | Add route `POST /object-predictions` | `counter/entrypoints/webapp.py` | `test_webapp.py`: 200 shape, sorted, threshold filtering, totals unchanged after the call | curl example returns 200 |
| M1.7 | Validation errors: missing file, bad or out-of-range threshold, non-image → 400 problem+json. Uses I1's helpers if M4 is done; otherwise minimal checks here, replaced by I1 later | `schemas.py`, `webapp.py` | `test_webapp.py`: each 400 case | invalid input returns 400 problem+json |
| M1.8 | Docs: OpenAPI path (Appendix A) and README curl example | `docs/openapi.yaml`, `README.md` | `openapi-spec-validator docs/openapi.yaml` (if M8 is set up) | spec and README match the behaviour. **Done in M8** (the README example since M1) |

**Acceptance criteria**
- [ ] `curl -F threshold=0.5 -F file=@resources/images/cat.jpg .../object-predictions` returns 200 with the `PredictionsResponse` shape.
- [ ] Only predictions with `score >= threshold` are returned, sorted by score descending.
- [ ] Calling it doesn't change `total_objects` (verified by a test).
- [ ] Invalid input returns 400 problem+json, as for `/object-count`.
- [ ] Existing `/object-count` tests still pass unchanged.

### M2: Relational DB adapter, PostgreSQL (P0)

**Goal:** `CountPostgresRepo` implementing `ObjectCountRepo`, selectable by config.

**Schema** (`docs/sql/001_object_counts.sql`)

```sql
CREATE TABLE IF NOT EXISTS object_counts (
    object_class VARCHAR(255) PRIMARY KEY,
    count        BIGINT       NOT NULL DEFAULT 0 CHECK (count >= 0),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

**Atomic increment** (same semantics as Mongo `$inc` + `upsert=True`)

```sql
INSERT INTO object_counts (object_class, count) VALUES (%s, %s)
ON CONFLICT (object_class)
DO UPDATE SET count = object_counts.count + EXCLUDED.count, updated_at = now();
```

MySQL equivalent:
`INSERT ... ON DUPLICATE KEY UPDATE count = count + VALUES(count)`.

**Code changes**

| File | Change |
|---|---|
| `requirements.txt` | `psycopg[binary,pool]` (plain SQL; no ORM needed for one table) |
| `counter/adapters/count_repo.py` | `CountPostgresRepo(dsn)`: a `ConnectionPool` created once; `ensure_schema()`; `update_values` runs all rows in **one transaction** (`executemany`); `read_values(classes)` uses `WHERE object_class = ANY(%s)` when classes are given, ordered by `object_class`; wraps `psycopg.OperationalError` in `RepositoryUnavailableError` |
| `counter/config.py` | `COUNT_REPO=memory\|mongo\|postgres` (default: `memory` in dev, `mongo` in prod for backwards compatibility); `POSTGRES_HOST/PORT/DB/USER/PASSWORD` or `DATABASE_URL` |
| `docker-compose.yml` | `postgres:16` service with healthcheck and volume |
| `.env.example`, `README.md` | Postgres variables and `make` usage |
| `tests/integration/test_count_repo_postgres.py` (new) | runs against a real Postgres via `testcontainers` |

**Steps**
1. Write the integration tests first (see acceptance criteria).
2. Implement `CountPostgresRepo` + schema creation.
3. Wire `COUNT_REPO` in `config.py`.
4. Add the compose service and docs.
5. Optional: a shared **repo contract test suite**, parametrised over memory/Mongo/Postgres, so every adapter has identical behaviour.

**Acceptance criteria**
- [ ] `update_values([cat:2])` twice → `read_values()` returns `cat:4`.
- [ ] `read_values(["cat"])` returns only cat; `read_values()` returns all; unknown classes are not returned.
- [ ] 20 concurrent `update_values([cat:1])` calls → `cat:20` (no lost updates).
- [ ] `COUNT_REPO=postgres make run-prod` + curl updates rows in `object_counts`.
- [ ] DB down → the API returns 503 problem+json.
- [ ] The same contract tests pass for the memory, Mongo and Postgres repos.

### M3: Code review: proposed improvements (P1, written)

Deliverable: a section in `docs/ANSWERS.md`. The items implemented in M4 are marked ✅.

**Setup and documentation**
- ✅ Pin Python 3.12 (3.14 breaks `numpy==1.26.4`; the README says ">= 3.10").
- ✅ Makefile, docker-compose, Dockerfile, `.env.example`, `pyproject.toml`.
- ✅ Fix `tmp/model/model_config.config` (references an unused `rfcn` model).
- ✅ Split runtime and dev dependencies.
- ✅ Pin transitive dependencies (lock file via `uv pip compile`).
- ✅ `.vscode/launch.json` hard-codes `ENV=prod`; add a dev configuration.

**Code**
- ✅ I1–I9 from M4.
- ✅ `count()` in `domain/predictions.py` uses `reduce` with a module-private function; `collections.Counter` is simpler.
- ✅ Type hints are incomplete (`execute(self, image, threshold)`); add them and run `mypy`.
- The TF Serving REST payload is a huge JSON array of pixels; gRPC or base64 `b64` input would be faster.
- `TFSObjectDetector` loads the label map in its constructor from a fixed file; make it injectable per model (needed for M5).

**Tests**
- `test_webapp.py` only asserts `!= None`; assert the body.
- `test_webapp.py` sends `model_name`, which is ignored.
- There are no adapter, failure-path or concurrency tests (addressed in M6).
- Tests depend on `ENV`: `create_app()` reads it, so `ENV=prod pytest` fails without services. Inject the action into `create_app(count_action=...)`.

**Acceptance criteria**
- [ ] Every proposal states the problem, the impact and the proposed fix.
- [ ] Implemented items are linked to the files or commits that implement them.

### M5: Multiple internal (private) models: setup changes (P1, written + implemented)

Deliverable: the Task 5 section in `docs/ANSWERS.md`, plus a working implementation (decided
with the user: written answer and a small implementation, local MLflow as the model registry).

**Decisions**
- **Registry:** a local MLflow Model Registry (SQLite `tmp/mlflow/registry.db` + artifact folder
  `tmp/mlflow/artifacts/`) stands in for a private company registry. MLflow is a setup-time
  tool only (own venv `.venv-models`, `requirements-models.txt`, `mlflow==3.17.2`); the app and
  TF Serving never call it. `mlflow-skinny` can't host a SQLite registry and MLflow 3's file
  backend is deprecated, hence the full package. MLflow 3's `register_model("runs:/...")` only
  accepts logged models, so versions are created with `MlflowClient.create_model_version`.
- **Models:** `ssd_mobilenet_v2` (the original SSD MobileNet v2 COCO, default) and
  `acme_shelf_detector` (public SSDLite MobileNet v2 COCO, 49 MB, published under an internal
  name to simulate an internal model; label map is a copy of COCO). Both from the official TF1
  detection model zoo, same SavedModel layout.
- **Patterns:** Strategy (`ObjectDetector` port), Factory (`DetectorFactory`, keyed by the
  manifest's `serving` type), Registry (`DetectorRegistry`). The domain doesn't change.
- **Selection:** optional `model_name` form field on both endpoints, not an endpoint per model;
  `GET /models`; responses include `model: {name, version}`. All models share the count store.
- **No automatic fallback model:** a missing model fails at startup; an unreachable one is 503.

**What was built**

| Step | Files |
|---|---|
| M5.1 Manifest + per-model label maps (moved `mscoco_label_map.json` to `models/labels/mscoco.json`) | `models/models.json`, `models/labels/`, `counter/adapters/model_manifest.py` |
| M5.2 Detector factory + label-map injection + version-pinned TF Serving URLs | `counter/adapters/detector_factory.py`, `object_detector.py` |
| M5.3 Detector registry; config builds it from manifest + `models.lock.json` (prod fails fast without pulled versions) | `counter/adapters/detector_registry.py`, `counter/config.py` |
| M5.4 `model_name`, `model` in responses, `GET /models`; CLI takes an optional model name | `counter/entrypoints/webapp.py`, `schemas.py`, `main.py` |
| M5.5 Registry workflow: `download` → `publish` (SHA-256 dedup, alias on first version) → `pull` (TF Serving layout, generated `model_config.config` with pinned versions, lock file); `promote`; Make targets incl. `mlflow-ui` | `scripts/model_registry.py`, `Makefile`, `requirements-models.txt` (replaces `scripts/download_model.sh`; `model_config.config` is now generated, no longer tracked) |
| M5.6 Docker/CI: image ships `models/`; compose mounts the lock file; CI `models` job; `pip-audit` covers MLflow | `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` |
| M5.7 Tests | `tests/adapters/test_models.py`, `tests/scripts/test_model_registry.py`, `test_webapp.py`, `test_config.py` |
| M5.8 Written answer | `docs/ANSWERS.md` (Task 5) |

**Acceptance criteria**
- [x] The answer covers storage, access control, serving, per-model metadata, selection, configuration and versioning.
- [x] `model_name=unknown` → 400 (lists the available models).
- [x] Two models are published, pulled and configured for TF Serving; both can be called (verified against a stub TF Serving with version-pinned URLs; real TF Serving needs Docker).

**Still proposals only:** a validated settings object (`pydantic-settings`), counts per model,
an evaluation gate before promotion, private container registry and service accounts in CI.

### M6: Testing improvements: option (a) implemented, (b) outlined (P1)

#### 6(a) Integration and e2e tests (implemented)

**Test pyramid and layout**

```
tests/
  unit/           domain + pure functions (no I/O)               make test
  api/            Flask test client with fakes injected          make test
  integration/    real Mongo/Postgres (testcontainers),          make test-integration
                  TFS adapter vs recorded responses (responses lib)
  e2e/            docker compose stack, real model, real DB      make test-e2e
  contract/       openapi.yaml validity (+ optional schemathesis)
```

| Level | Covers | Tooling |
|---|---|---|
| Unit | `over_threshold`, `count`, sorting, `CountDetectedObjects`, `DetectObjects` | pytest, `Mock` |
| API | both endpoints: 200 bodies, every 400/413/503 case, problem+json shape | Flask test client; `create_app(count_action=..., detect_action=...)` with fakes |
| Integration (repos) | memory/Mongo/Postgres contract suite, concurrency | `testcontainers[mongodb,postgres]` |
| Integration (TFS adapter) | request payload format, response parsing, class-id mapping, timeout → `DetectorUnavailableError`, RGBA/greyscale images | `responses` with a recorded TF Serving JSON fixture |
| E2E | `cat.jpg` → contains `cat`; totals increase across two calls; `/object-predictions` doesn't change totals | `docker compose up`, `requests` against `localhost` |
| Contract | spec valid; responses match the schemas | `openapi-spec-validator`, optional `schemathesis` |

**Changes:** pytest markers `integration`, `e2e` in `pyproject.toml`; fixtures in
`tests/conftest.py`; `tests/fixtures/tfs_response_cat.json`; the Makefile targets from M7.

**Implemented (M6a)** — the strategy and theory are in [`docs/TESTING.md`](docs/TESTING.md),
the summary in `docs/ANSWERS.md` (Task 6(a)). Differences from the sketch above:
- Layout: unit and component tests mirror the code (`tests/domain/`, `tests/adapters/`,
  `tests/entrypoints/`); integration and e2e tests are grouped by kind (`tests/integration/`,
  `tests/e2e/`); shared database fixtures in `tests/conftest.py`.
- TF Serving integration uses an in-process stub HTTP server replaying
  `tests/fixtures/tfs_predict_response.json` (instead of the `responses` library), so the real
  HTTP request is exercised; it needs no Docker and runs in `make test`.
- E2E runs against the Compose stack incl. the app **container** and both real models pulled
  from the MLflow registry (`make e2e`, CI job `e2e`), once with MongoDB and once with
  PostgreSQL; every response is validated against `docs/openapi.yaml`.
- Markers: `integration`, `models`, `e2e`. Coverage: `pytest-cov`, `fail_under = 90`.
- The new API-level concurrency test found a race in `CountPostgresRepo` schema creation
  (unique violation on `pg_type`), fixed with `pg_advisory_xact_lock`.

**Acceptance criteria**
- [x] `make test` runs in under 10 s without Docker (124 tests, ~6 s).
- [x] `make test-integration` and `make test-e2e` pass with Docker (CI jobs `integration` and `e2e`).
- [x] Every status code documented in OpenAPI has at least one test (enforced by `test_every_documented_status_code_is_tested`).
- [x] Domain + adapter line coverage ≥ 85% (`make coverage`: ~98% of `counter/`, CI gate 90%).

#### 6(b) Multiple deep-learning frameworks (outline only, in `docs/ANSWERS.md`)

**Status:** done as an outline (user decision 2026-10-27: not implemented, to avoid a third serving
container, a second model format and a heavier CI job for an optional task). Diagram:
`docs/diagrams/m6b_architecture.dot` (source) and `.svg`.

1. The `ObjectDetector` port already isolates the framework, and since M5 the `serving` field in
   `models/models.json` picks the adapter in `DetectorFactory`. Add **one adapter per serving
   protocol, not per framework**: `KServeV2ObjectDetector` (KServe v2 REST), with builders `ovms`
   (OpenVINO Model Server, CPU, small image: first step) and `triton` (Triton Inference Server:
   ONNX Runtime, PyTorch, TensorFlow up to 25.02, OpenVINO, TensorRT; `KIND_CPU`/`KIND_GPU`).
2. Per-model pre/post-processing in the manifest (input name/dtype/layout, output names, box order,
   pixel vs normalised coordinates, class-id offset, label map); defaults match today's TF models.
3. Model export: SavedModel, TorchScript, ONNX (`tf2onnx`, `torch.onnx.export`), TensorRT engines;
   the M5 registry flow stays, `make pull-models` would also write `config.pbtxt` / OVMS `config.json`.
4. Tests: unit, stub KServe v2 server (no Docker), shared adapter contract test, e2e with OVMS + an
   ONNX SSD-MobileNet in CI; full Triton (15-20 GB image) and TensorRT only on a GPU runner.
5. First step if built: a spike running OVMS with the ONNX model (risk: NMS/loop ops in the
   converted model). Rough effort: 2-3 days (OVMS path incl. CI) + 1-2 days (Triton).

---

## 7. Optional enhancements

### O1: Authentication and authorization (P2)

**Assumption:** the clients are internal services or scripts, not end users. No user
management is needed.

**Phase 1: API key (simplest)**

| Item | Design |
|---|---|
| Transport | header `X-API-Key: <key>` |
| Storage | keys in env/secret (`API_KEYS=key1:role1,key2:role2`), compared with a constant-time comparison; never logged |
| Enable/disable | `AUTH_ENABLED=false` by default in dev, `true` in prod |
| Exempt | `/health`, `/docs`, `/openapi.*` |

**Phase 2: JWT / OAuth2 (if integrating with a company IdP)**

- `Authorization: Bearer <jwt>`, validated against the IdP's JWKS (issuer, audience, expiry).
- Scopes/roles drive authorization:

| Endpoint | Required scope | Reason |
|---|---|---|
| `POST /object-predictions` | `predictions:read` | read-only |
| `POST /object-count` | `counts:write` | mutates stored totals |
| `GET /object-counts` (O2) | `counts:read` | read totals |
| `DELETE /object-counts` (admin, optional) | `counts:admin` | resets totals |

**Status codes:** 401 (missing/invalid credentials, with `WWW-Authenticate`), 403 (valid
credentials, missing scope). Both use problem+json.

**OpenAPI:** add `components.securitySchemes` (`ApiKeyAuth` in header and/or `bearerAuth`)
and `security:` per operation; Swagger UI shows an "Authorize" button.

**Per framework**

| Flask | FastAPI | Spring Boot |
|---|---|---|
| `before_request` hook or a `@require_scope("counts:write")` decorator; `PyJWT` for JWT | `Security(APIKeyHeader(...))` dependency; `OAuth2PasswordBearer`/`HTTPBearer` + `python-jose`/`PyJWT`; `Security(..., scopes=[...])` | `spring-boot-starter-security`; API key via a `OncePerRequestFilter`; JWT via `spring-boot-starter-oauth2-resource-server` (`issuer-uri`); `@PreAuthorize("hasAuthority('SCOPE_counts:write')")` |

**Acceptance criteria**
- [ ] With auth enabled: no key → 401; wrong scope → 403; valid → 200.
- [ ] With auth disabled (dev), everything works without headers.
- [ ] Keys/tokens never appear in logs.
- [ ] The OpenAPI spec documents the security scheme and the 401/403 responses.

### O2–O5 (P2)

| ID | Item | Acceptance criteria |
|---|---|---|
| O2 ✅ | `GET /health`, `GET /health/ready`, `GET /object-counts` (section 5.6) | used by compose healthchecks; documented in OpenAPI. Done in PR #20; readiness reports one check per served model (`checks.detectors.<model>`), since M5 serves several |
| O3 | GitHub Actions: `make lint test` on every push, `make test-integration` with service containers | green badge in the README |
| O4 | JSON logs with request ID; Prometheus `/metrics` (request count, latency, detector latency) | request ID returned in an `X-Request-ID` header |
| O5 | Rate limiting (`flask-limiter` / `slowapi` / Bucket4j) | 429 problem+json when exceeded |

---

## 8. Optional: Flask → FastAPI migration

**Principle:** only `counter/entrypoints/`, `config.py` wiring, the tests and the tooling
change. The domain and adapters stay untouched, which shows the value of the hexagonal design.
The JSON contract (section 5) must not change, apart from the port.

### 8.1 Requirements

| # | Requirement |
|---|---|
| F1 | Same endpoints, paths, form fields, defaults and response JSON as the Flask version |
| F2 | Same error format (problem+json) and status codes. FastAPI's default 422 for validation errors is **overridden to 400** for parity. |
| F3 | Upload limit of 10 MB enforced (FastAPI has no `MAX_CONTENT_LENGTH`: check `file.size` or use middleware) → 413 |
| F4 | OpenAPI generated automatically and equivalent to `docs/openapi.yaml` (examples, all status codes) |
| F5 | Blocking adapters (`requests`, `pymongo`, `psycopg`) must not block the event loop |
| F6 | All existing tests are ported and pass; same curl commands work on port 8000 |
| F7 | Dev and prod wiring keep working (`ENV`, `COUNT_REPO`) |

### 8.2 Changes

| Area | Flask today | FastAPI |
|---|---|---|
| Dependencies | `Flask`, `flask-swagger-ui` | `fastapi`, `uvicorn[standard]`, `python-multipart`, `pydantic>=2`, `httpx` (TestClient); remove Flask |
| App | `create_app()` → `Flask` | `create_app()` → `FastAPI(title="Object Counter", version="1.0.0")`; module-level `app = create_app()` |
| Request DTO | manual `parse_*_request(request)` | `file: UploadFile = File(...)`, `threshold: float = Form(0.5, ge=0.0, le=1.0)`, `model_name: str \| None = Form(None)` |
| Response DTO | dict built by hand | Pydantic models `BoxSchema`, `PredictionSchema`, `ObjectCountSchema`, `CountResponseSchema`, `PredictionsResponseSchema`, `ProblemSchema` in `counter/entrypoints/schemas.py`; mapped from domain dataclasses (`model_validate(..., from_attributes=True)`); the domain doesn't import Pydantic |
| Wiring | action built inside `create_app` | `Depends(get_count_action)` / `Depends(get_detect_action)` with `@lru_cache`; tests use `app.dependency_overrides` |
| Errors | `@app.errorhandler` | `@app.exception_handler(RequestValidationError)` → 400 problem+json; handlers for the domain errors → 400/503; `HTTPException` → problem+json |
| Sync/async | sync | endpoints declared with plain `def` so FastAPI runs them in a threadpool (F5). Later option: `httpx.AsyncClient` in the TFS adapter + async ports. |
| Docs | `docs/openapi.yaml` + Swagger UI | generated `/docs`, `/redoc`, `/openapi.json`; `responses={400: {"model": ProblemSchema}, ...}` and `openapi_examples` per endpoint |
| Server | `app.run(debug=True)` / gunicorn | `uvicorn counter.entrypoints.webapp:app --reload --port 8000` (dev); `gunicorn -k uvicorn.workers.UvicornWorker` (prod) |
| Tests | `app.test_client()` | `fastapi.testclient.TestClient(app)`; `client.post(url, files={"file": ...}, data={"threshold": "0.9"})` |
| Tooling | `.vscode/launch.json` uses the `flask` module | `uvicorn` module; update `Makefile`, `Dockerfile` CMD, README, `.env.example` |
| Auth (O1) | decorator | `Security(...)` dependencies; appear in OpenAPI automatically |

### 8.3 Sketch

```python
@app.post("/object-count", response_model=CountResponseSchema,
          responses={400: {"model": ProblemSchema}, 413: {"model": ProblemSchema},
                     503: {"model": ProblemSchema}})
def object_count(file: UploadFile = File(...),
                 threshold: float = Form(0.5, ge=0.0, le=1.0),
                 action: CountDetectedObjects = Depends(get_count_action)):
    image = read_image_upload(file)          # size + type check, raises ValidationError
    return to_count_response_dto(action.execute(image, threshold))
```

### 8.4 Steps

1. Add the dependencies; create `schemas.py` with the Pydantic DTOs matching section 5.2.
2. Port the routes; add the exception handlers (422 → 400, domain errors).
3. Port the tests to `TestClient`; add a test that compares the generated `/openapi.json` paths, status codes and schemas with `docs/openapi.yaml`.
4. Update the Makefile, Dockerfile, README and `.vscode/launch.json`.
5. Remove Flask.

### 8.5 Acceptance criteria

- [ ] All tests pass; the same curl commands (port 8000) return byte-for-byte the same JSON shape.
- [ ] Invalid `threshold` returns **400** problem+json (not 422).
- [ ] `/docs` lists every endpoint with all status codes and examples.
- [ ] `git diff` shows no changes under `counter/domain/` or `counter/adapters/`.

---

## 9. Optional: equivalent implementation in Spring Boot

**Principle:** keep the same hexagonal layers and the **same API contract** (section 5 /
Appendix A). The model keeps running in **TF Serving**; Spring Boot replaces only the Python
service. It lives in the `spring-boot/` directory of this repository, with its own Maven
build (see section 10).

### 9.1 Stack

Java 21, Spring Boot 3.x, Maven wrapper (`./mvnw`).

| Purpose | Dependency |
|---|---|
| REST API | `spring-boot-starter-web` |
| Validation | `spring-boot-starter-validation` |
| MongoDB adapter | `spring-boot-starter-data-mongodb` |
| PostgreSQL adapter | `spring-boot-starter-jdbc` + `org.postgresql:postgresql` + `flyway-core` |
| OpenAPI / Swagger | `springdoc-openapi-starter-webmvc-ui` |
| Health / metrics (O2/O4) | `spring-boot-starter-actuator` (+ `micrometer-registry-prometheus`) |
| Auth (O1) | `spring-boot-starter-security`, `spring-boot-starter-oauth2-resource-server` |
| Tests | JUnit 5, Mockito, AssertJ, `spring-boot-testcontainers`, Testcontainers (Mongo, Postgres), WireMock |

### 9.2 Package layout and mapping

```
com.niq.counter
  domain/model      Box, Prediction, ObjectCount, CountResponse   (records)
  domain/port       ObjectDetector, ObjectCountRepo               (interfaces)
  domain/service    CountDetectedObjects, DetectObjects, Predictions (no Spring annotations)
  domain/error      InvalidImageException, DetectorUnavailableException, RepositoryUnavailableException
  adapter/detector  TfsObjectDetector, FakeObjectDetector, LabelMap
  adapter/repo      MongoObjectCountRepo, JdbcObjectCountRepo, InMemoryObjectCountRepo
  web               ObjectCountController, dto/*, ProblemHandler (@RestControllerAdvice)
  config            DomainConfig (@Bean wiring), AppProperties (@ConfigurationProperties)
```

| Python | Spring Boot (framework-specific notes) |
|---|---|
| `@dataclass` models | Java `record`s, immutable |
| `ABC` ports | `interface`s |
| `over_threshold`, `count` (`reduce`) | streams: `filter(p -> p.score() >= t)`, `collect(groupingBy(Prediction::className, counting()))` |
| `CountDetectedObjects` | plain class; turned into a bean in `DomainConfig` via `@Bean` so the domain has no Spring dependency |
| `config.py` + `ENV` dispatch | **Spring profiles** `dev` / `prod`; `@Profile("dev") @Bean FakeObjectDetector`; `@ConditionalOnProperty(name="counter.repo", havingValue="postgres")` replaces `COUNT_REPO` |
| `os.environ.get(...)` | `application.yml` + `application-prod.yml`, bound to `@ConfigurationProperties("counter")` records; env vars override (`COUNTER_TFS_HOST`) |
| `TFSObjectDetector` (`requests`, Pillow, numpy) | `RestClient` with connect/read timeouts; `ImageIO.read` → `BufferedImage` → `int[1][h][w][3]` via `getRGB`; Jackson for JSON; label map from `classpath:mscoco_label_map.json`; `RestClientException` → `DetectorUnavailableException`; `ImageIO.read == null` → `InvalidImageException` |
| `CountMongoDBRepo` (`$inc`, upsert) | `MongoTemplate.upsert(query(where("object_class").is(c)), new Update().inc("count", n), "counter")` |
| `CountPostgresRepo` | `JdbcClient` with the same `ON CONFLICT ... DO UPDATE` SQL; `@Transactional` on `updateValues`; schema via Flyway `V1__object_counts.sql` |
| `CountInMemoryRepo` (dict) | `ConcurrentHashMap.merge(cls, n, Long::sum)`, thread-safe (Flask dev is single-threaded, Tomcat isn't) |
| Flask route | `@RestController`, `@PostMapping(value="/object-count", consumes=MULTIPART_FORM_DATA_VALUE, produces=APPLICATION_JSON_VALUE)` |
| Form parsing | `@RequestPart("file") MultipartFile file`, `@RequestParam(defaultValue="0.5") @DecimalMin("0.0") @DecimalMax("1.0") double threshold`, `@Validated` on the controller |
| `MAX_CONTENT_LENGTH` | `spring.servlet.multipart.max-file-size=10MB`, `max-request-size=10MB` → `MaxUploadSizeExceededException` → 413 |
| `jsonify` snake_case | `spring.jackson.property-naming-strategy=SNAKE_CASE` (Java fields are camelCase) |
| Error handlers | `@RestControllerAdvice extends ResponseEntityExceptionHandler`, returning `ProblemDetail` (native RFC 7807); `spring.mvc.problemdetails.enabled=true`; map `HandlerMethodValidationException`/`ConstraintViolationException`/`MissingServletRequestPartException`/`MethodArgumentTypeMismatchException` → 400, domain exceptions → 400/503 |
| `debug.py` (Pillow drawing) | optional `Graphics2D` writer behind `counter.debug-images=true` |
| `main.py` CLI | optional `CommandLineRunner` under a `cli` profile |
| Swagger (contract-first YAML) | springdoc: `@Operation`, `@ApiResponse(responseCode="400", content=@Content(schema=@Schema(implementation=ProblemDetail.class)))`, `@Schema(example=...)` on DTOs; UI at `/swagger-ui.html`, spec at `/v3/api-docs` |
| Health (O2) | Actuator `/actuator/health` with Mongo/DB indicators built in |
| Auth (O1) | `SecurityFilterChain` bean; `oauth2ResourceServer(jwt)` or an API-key filter; `@PreAuthorize` per endpoint |
| pytest | JUnit 5 (see 9.4) |
| `requirements.txt`, venv | `pom.xml`, Maven wrapper |
| Dockerfile (python) | `./mvnw spring-boot:build-image` (Buildpacks) or Jib; added to the same `docker-compose.yml` |

### 9.3 Controller sketch

```java
@RestController
@Validated
class ObjectCountController {
    private final CountDetectedObjects countAction;
    private final DetectObjects detectAction;

    @PostMapping(value = "/object-count", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @Operation(summary = "Count objects above threshold and update totals")
    CountResponseDto count(@RequestPart("file") MultipartFile file,
                           @RequestParam(defaultValue = "0.5") @DecimalMin("0.0") @DecimalMax("1.0") double threshold)
            throws IOException {
        return CountResponseDto.from(countAction.execute(file.getInputStream(), threshold));
    }
}
```

### 9.4 Tests

| Level | Tooling |
|---|---|
| Domain | JUnit 5 + Mockito: the same cases as `tests/domain` |
| Controller / API | `@WebMvcTest` + `MockMvc.perform(multipart("/object-count").file(...).param("threshold","0.9"))`; asserts JSON and problem+json |
| Repos | `@DataMongoTest` / `@JdbcTest` + `@Testcontainers` with `@ServiceConnection` (`MongoDBContainer`, `PostgreSQLContainer`); the shared contract tests as an abstract base class |
| TFS adapter | WireMock returning the recorded TF Serving response; timeout → `DetectorUnavailableException` |
| E2E | `@SpringBootTest(webEnvironment = RANDOM_PORT)` + Testcontainers (TF Serving container with the model volume) |
| Contract | compare `/v3/api-docs` with `docs/openapi.yaml` |

### 9.5 Run

```bash
./spring-boot/mvnw -f spring-boot/pom.xml spring-boot:run -Dspring-boot.run.profiles=dev   # from repo root, http://localhost:8080
curl -F "threshold=0.9" -F "file=@resources/images/boy.jpg" http://localhost:8080/object-count
open http://localhost:8080/swagger-ui.html
```

**Machine setup:** JDK 21 (`sudo apt install -y openjdk-21-jdk`, or SDKMAN without sudo). The
Maven wrapper downloads Maven itself.

### 9.6 Acceptance criteria

- [ ] The same curl commands (port 8080) return the same JSON shape as the Python service (snake_case).
- [ ] Every status code in section 5 is produced and tested.
- [ ] `dev` profile runs with no external services; `prod` profile uses TF Serving + Mongo or Postgres.
- [ ] Swagger UI lists both endpoints with schemas, examples and error responses.
- [ ] `domain` packages have no `org.springframework` imports (optionally enforced with an ArchUnit test).

---

## 10. Repository strategy: Flask, FastAPI and Spring Boot

### 10.1 Recommendation

| Implementation | Relationship to the Flask code | Where it lives |
|---|---|---|
| Flask (now) | the graded deliverable | repository root, unchanged layout |
| FastAPI (O6) | **replaces** Flask: a migration, not a second implementation | a feature branch (`feat/o6-fastapi-migration`), merged into `main` by PR; Flask is removed |
| Spring Boot (O7) | **runs alongside** Python: a parallel implementation of the same contract | **same repository**, top-level `spring-boot/` directory, developed on `feat/o7-spring-boot` and merged into `main` |

**Decision:** one repository (monorepo). Branches are used only for short-lived feature work,
never to hold a long-lived alternative implementation. No separate repository for now.

The key distinction: a **migration** changes the same code over time, which is what branches
are for. A **parallel implementation** must exist at the same time as the original, which is
what directories (or repositories) are for.

### 10.2 Options compared

| Criterion | Same repo, separate directories | Separate long-lived branches | Separate repositories |
|---|---|---|---|
| Shared API contract (`docs/openapi.yaml`) | one file, one source of truth | copied per branch, **drifts** | copied or published as a package; drifts without extra tooling |
| Shared test images, label map, `docker-compose.yml` (TF Serving, Mongo, Postgres) | shared directly | duplicated per branch | duplicated, or a third "infra" repo |
| Parity tests (same requests, same JSON from both services) | one e2e suite runs against both in one CI job | impossible in one checkout | needs cross-repo CI orchestration |
| A contract change updates both implementations | **one atomic PR** | one PR per branch, easy to forget | coordinated PRs in two repos |
| What reviewers or evaluators see | everything on `main`, one README | `main` shows only one implementation; the other is hidden in a branch | two links to two READMEs |
| Merging and history | normal | branches never merge (different languages), so `main` and the branch diverge forever; fixes must be cherry-picked | independent histories, which is fine |
| Toolchain separation (pip vs Maven) | needs path-filtered CI and a clear layout | natural | natural |
| Independent releases, versioning and access control | harder (shared tags and permissions) | awkward | **natural** |
| Repository size and CI time | grows with both | per branch | smallest |
| Fit for the assignment (one fork to submit) | **best** | poor | poor |

**Why not branches:** a branch is a line of change to the same code, meant to be merged back.
A Java implementation can never be merged into a Python `main`, so the branch becomes a
permanent fork inside the repo. It would hide one implementation from reviewers, duplicate
the contract and infrastructure, and make side-by-side testing impossible.

**Why not separate repos (yet):** the two services share a contract, test data and
infrastructure, and are worked on by one person for one submission. Splitting them adds
coordination cost (contract drift, cross-repo e2e tests, two places to review) with none of
the benefits, which only appear with separate teams or release cycles.

**Why Python stays at the root:** the Flask service is the mandatory, graded deliverable.
Moving it into `python/` would churn every path (README, Makefile, imports, the CWD-relative
resource paths, `.vscode/launch.json`) for an optional extra. Spring Boot is self-contained in
its own directory instead.

### 10.3 When to split into separate repositories

Revisit this decision, and extract `spring-boot/` with history using
`git subtree split -P spring-boot -b spring-boot-only`, if any of these become true:

- different teams own the two services, or they need different access permissions
- they need independent release cycles, versions or deployment pipelines
- CI time or repo size becomes a problem despite path filters
- the contract is published as a versioned artifact (e.g. an OpenAPI package or a generated client), so each repo can depend on a version of it

### 10.4 Target layout

```
object-counter-vibe-coding/
  counter/                  Python service (Flask now, FastAPI after O6)
  tests/                    Python unit, API and integration tests
  tests/e2e/                e2e + parity tests, black-box over HTTP; BASE_URL selects the service
  docs/
    openapi.yaml            the shared contract for every implementation
    ANSWERS.md
  resources/images/         shared test images
  scripts/download_model.sh
  docker-compose.yml        tfserving, mongo, postgres + app-python (:5000) and app-java (:8080) under profiles
  Makefile                  Python targets + java-* targets that call ./spring-boot/mvnw
  spring-boot/              Spring Boot service, fully self-contained
    pom.xml, mvnw, .mvn/
    src/main/java/com/niq/counter/...
    src/test/java/...
    README.md               Java-specific setup; links to the root README and the contract
  README.md                 entry point for both services
  plan.md
```

**Sharing rules**

| Shared asset | How Spring Boot uses it |
|---|---|
| `docs/openapi.yaml` | contract test compares `/v3/api-docs` with it |
| `models/models.json`, `models/labels/` | the same model manifest and label maps, read from `../models/` (no duplicate files) |
| `resources/images/` | test fixtures, referenced as `../resources/images/` |
| `docker-compose.yml` | `docker compose --profile java up` starts `app-java` with the shared infrastructure |
| Databases | each service uses its own database name (`counter_python`, `counter_java`) so their totals and tests don't interfere |

### 10.5 Git workflow

- `main` always builds and passes all tests. No direct commits; every change goes through a PR.
- One short-lived branch per plan item, named `<type>/<plan-id>-<topic>`: `feat/m1-predictions-endpoint`, `feat/m2-postgres-repo`, `chore/m7-makefile-compose`, `feat/o6-fastapi-migration`, `feat/o7-spring-boot`.
- Squash-merge to keep `main` readable; delete the branch after merging.
- A PR that changes `docs/openapi.yaml` must update **every** implementation that exists on `main`, plus the parity tests, in the same PR.
- Tag milestones that matter for the submission, for example `v1.0-assignment` (all mandatory items) and `v1.1-spring-boot`.

### 10.6 CI (with O3)

| Job | Runs when these paths change | Steps |
|---|---|---|
| `python` | `counter/**`, `tests/**`, `requirements*.txt`, `pyproject.toml` | `make lint test test-integration` |
| `java` | `spring-boot/**` | `./mvnw -B verify` (JDK 21) |
| `contract-parity` | `docs/openapi.yaml`, `tests/e2e/**`, or either service | start both services in compose, run `tests/e2e` with `BASE_URL=:5000` and `BASE_URL=:8080` |

### 10.7 Acceptance criteria

- [ ] Spring Boot code lives only under `spring-boot/`; no Java build files at the repo root.
- [ ] The Python layout at the root is unchanged by O7.
- [ ] `docs/openapi.yaml` exists once, and both services are tested against it.
- [ ] The same e2e/parity suite passes against both services.
- [ ] The root README explains both services and links to `spring-boot/README.md`.
- [ ] No long-lived implementation branches: after merging, `main` contains everything.

---

## Appendix A: OpenAPI 3 contract (`docs/openapi.yaml`)

This is the source of truth for all three implementations. Auth parts apply only when O1 is
done.

```yaml
openapi: 3.0.3
info:
  title: Object Counter API
  version: 1.0.0
  description: >
    Detects objects in an image, counts those whose confidence score is at or above a
    threshold (grouped by class) and keeps accumulated totals.
servers:
  - url: http://localhost:5000
    description: Flask (dev)
tags:
  - name: counting
  - name: predictions
  - name: models

paths:
  /object-count:
    post:
      tags: [counting]
      operationId: countObjects
      summary: Count objects above the threshold and update the totals
      description: Not idempotent. Each call adds the detected counts to the stored totals.
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema: { $ref: '#/components/schemas/ImageRequest' }
            encoding:
              file: { contentType: 'image/jpeg, image/png' }
      responses:
        '200':
          description: Counts for this image and accumulated totals
          content:
            application/json:
              schema: { $ref: '#/components/schemas/CountResponse' }
              example:
                current_objects: [ { object_class: person, count: 1 } ]
                total_objects:   [ { object_class: cat, count: 3 }, { object_class: person, count: 1 } ]
                model: { name: ssd_mobilenet_v2, version: '1' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '413': { $ref: '#/components/responses/PayloadTooLarge' }
        '500': { $ref: '#/components/responses/InternalError' }
        '503': { $ref: '#/components/responses/ServiceUnavailable' }

  /object-predictions:
    post:
      tags: [predictions]
      operationId: listPredictions
      summary: List predictions above the threshold
      description: Read-only. Does not change the stored totals.
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema: { $ref: '#/components/schemas/ImageRequest' }
            encoding:
              file: { contentType: 'image/jpeg, image/png' }
      responses:
        '200':
          description: Predictions with score >= threshold, sorted by score (descending)
          content:
            application/json:
              schema: { $ref: '#/components/schemas/PredictionsResponse' }
              example:
                threshold: 0.5
                count: 1
                predictions:
                  - class_name: cat
                    score: 0.9991
                    box: { xmin: 0.3673, ymin: 0.2783, xmax: 0.7358, ymax: 0.6989 }
                model: { name: ssd_mobilenet_v2, version: '1' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '413': { $ref: '#/components/responses/PayloadTooLarge' }
        '500': { $ref: '#/components/responses/InternalError' }
        '503': { $ref: '#/components/responses/ServiceUnavailable' }

  /models:
    get:
      tags: [models]
      operationId: listModels
      summary: List the models that model_name accepts
      responses:
        '200':
          description: Served models and the default one
          content:
            application/json:
              schema: { $ref: '#/components/schemas/ModelsResponse' }
              example:
                default_model: ssd_mobilenet_v2
                models:
                  - { name: acme_shelf_detector, version: '1' }
                  - { name: ssd_mobilenet_v2, version: '1' }

components:
  schemas:
    ImageRequest:
      type: object
      required: [file]
      properties:
        file:
          type: string
          format: binary
          description: JPEG or PNG image, max 10 MB
        threshold:
          type: number
          format: float
          minimum: 0.0
          maximum: 1.0
          default: 0.5
          description: Minimum confidence score (inclusive)
        model_name:
          type: string
          description: Model to use (see GET /models); empty or missing means the default model
          example: acme_shelf_detector
    Box:
      type: object
      description: Bounding box, coordinates normalised to [0, 1]
      required: [xmin, ymin, xmax, ymax]
      properties:
        xmin: { type: number, minimum: 0, maximum: 1 }
        ymin: { type: number, minimum: 0, maximum: 1 }
        xmax: { type: number, minimum: 0, maximum: 1 }
        ymax: { type: number, minimum: 0, maximum: 1 }
    Prediction:
      type: object
      required: [class_name, score, box]
      properties:
        class_name: { type: string, example: cat }
        score: { type: number, minimum: 0, maximum: 1, example: 0.9991 }
        box: { $ref: '#/components/schemas/Box' }
    ObjectCount:
      type: object
      required: [object_class, count]
      properties:
        object_class: { type: string, example: cat }
        count: { type: integer, minimum: 0, example: 2 }
    Model:
      type: object
      description: The model that produced a response
      required: [name, version]
      properties:
        name: { type: string, example: ssd_mobilenet_v2 }
        version:
          type: string
          nullable: true
          description: Registry version served by TF Serving; null in dev (fake detectors)
          example: '1'
    ModelsResponse:
      type: object
      required: [default_model, models]
      properties:
        default_model: { type: string, example: ssd_mobilenet_v2 }
        models:
          type: array
          items: { $ref: '#/components/schemas/Model' }
    CountResponse:
      type: object
      required: [current_objects, total_objects, model]
      properties:
        current_objects:
          type: array
          items: { $ref: '#/components/schemas/ObjectCount' }
        total_objects:
          type: array
          items: { $ref: '#/components/schemas/ObjectCount' }
        model: { $ref: '#/components/schemas/Model' }
    PredictionsResponse:
      type: object
      required: [threshold, count, predictions, model]
      properties:
        threshold: { type: number, minimum: 0, maximum: 1 }
        count: { type: integer, minimum: 0 }
        predictions:
          type: array
          items: { $ref: '#/components/schemas/Prediction' }
        model: { $ref: '#/components/schemas/Model' }
    FieldError:
      type: object
      required: [field, message]
      properties:
        field: { type: string }
        message: { type: string }
    Problem:
      type: object
      description: RFC 7807 problem details
      required: [title, status]
      properties:
        type: { type: string, format: uri, default: about:blank }
        title: { type: string }
        status: { type: integer }
        detail: { type: string }
        instance: { type: string }
        errors:
          type: array
          items: { $ref: '#/components/schemas/FieldError' }

  responses:
    BadRequest:
      description: Invalid request (missing/invalid field, unreadable image, unknown model)
      content:
        application/problem+json:
          schema: { $ref: '#/components/schemas/Problem' }
          examples:
            invalidThreshold:
              value:
                title: Invalid request
                status: 400
                detail: Request validation failed
                instance: /object-count
                errors: [ { field: threshold, message: must be between 0.0 and 1.0 } ]
            missingFile:
              value:
                title: Invalid request
                status: 400
                detail: Request validation failed
                errors: [ { field: file, message: is required } ]
            invalidImage:
              value:
                title: Invalid image
                status: 400
                detail: The uploaded file is not a valid JPEG or PNG image
    PayloadTooLarge:
      description: Upload larger than 10 MB
      content:
        application/problem+json:
          schema: { $ref: '#/components/schemas/Problem' }
          example: { title: Payload too large, status: 413, detail: Maximum upload size is 10 MB }
    InternalError:
      description: Unexpected error
      content:
        application/problem+json:
          schema: { $ref: '#/components/schemas/Problem' }
          example: { title: Internal server error, status: 500 }
    ServiceUnavailable:
      description: Object detector or count repository unavailable
      content:
        application/problem+json:
          schema: { $ref: '#/components/schemas/Problem' }
          example: { title: Object detector unavailable, status: 503, detail: TF Serving did not respond within 10 s }

  # Optional (O1): enable and add `security:` to operations
  # securitySchemes:
  #   ApiKeyAuth: { type: apiKey, in: header, name: X-API-Key }
  #   bearerAuth: { type: http, scheme: bearer, bearerFormat: JWT }
```

---

## Appendix B: Definition of done (whole assignment)

- [ ] **Mandatory:** M1, M2, M4, M7, M8 implemented; M3, M5, M6(b) written in `docs/ANSWERS.md`; M6(a) tests implemented.
- [ ] `make setup && make test` passes on a clean clone; `make up && make run-prod` works with the real model.
- [ ] README: overview, prerequisites, setup, run, test, API docs link, configuration table, links to `docs/ANSWERS.md` and `plan.md`.
- [ ] `docs/openapi.yaml` is valid and matches the implementation; Swagger UI at `/docs`.
- [ ] Every ambiguity in section 3 is either confirmed or its assumption is documented in `docs/ANSWERS.md`.
- [ ] Clean code: `make lint` passes; no `print` calls; type hints on public functions.
- [ ] **Optional** items (O1–O8) are each done completely (code + tests + docs) or not started. Nothing half-finished is merged.
