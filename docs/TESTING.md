# Testing strategy

How this project is tested, why each kind of test exists, and how to run it. This answers Task 6(a) ("improve the testing by adding integration and e2e tests"); the summary is in [`ANSWERS.md`](ANSWERS.md#task-6a-integration-and-end-to-end-tests).

## 1. What tests are for

A test suite is worth its cost when it gives:

1. **Confidence to change code.** Refactoring (e.g. the M4 and M5 rewrites of the adapters and the composition root) is safe only if behaviour is pinned down by tests.
2. **Fast feedback.** A developer should learn about a mistake in seconds, before pushing, not from a production incident.
3. **Executable documentation.** A test such as `test_unknown_model_is_rejected` states a rule more precisely than prose.
4. **Defect localisation.** When a test fails, the failing level (unit, integration, e2e) should point at the broken part.

No single kind of test gives all four. Fast tests can't prove that real components fit together; realistic tests are slow and fail for many reasons. A strategy mixes them.

## 2. The levels

| Level | Question it answers | Real | Replaced | Speed | Typical failure means |
|---|---|---|---|---|---|
| **Unit** | Is this function or class correct on its own? | the code under test | everything it calls | ms | a logic bug in that unit |
| **Component / API** | Does the app handle requests correctly? | the whole Flask app | external systems (fakes) | ms | wrong validation, routing, status code or body |
| **Contract** | Does the app behave as its published API says? | app + `docs/openapi.yaml` | external systems | ms | the spec and the code disagree |
| **Integration** | Does our code work with a real external system? | our code + one real dependency (database, HTTP server) | the rest | 0.1–1 s | wrong SQL, wrong protocol use, concurrency, configuration |
| **End-to-end (e2e)** | Does the deployed system work for a client? | everything: containers, network, real models, real databases | nothing | seconds | deployment, wiring or environment problems, or anything missed below |

The usual shape is the **test pyramid**: many unit and component tests at the bottom, fewer integration tests, few e2e tests at the top. The cost and flakiness of a test grow with every real component it includes, while its power to point at the exact defect shrinks. The pyramid is a budget, not a rule: a level is worth having when it catches defects the levels below can't.

```
            e2e        20   real stack in Docker, real models, monitoring, drift  (CI: e2e job)
        integration    30   real Postgres/Mongo, + 15 against a stub TF Serving
     contract + API    81   Flask app, OpenAPI validation, CLIs
  unit + component   160   domain, drift, evaluation, adapters, config, logging, metrics, registry scripts
```

## 3. Why hexagonal architecture makes this cheap

The domain only talks to **ports** (`ObjectDetector`, `ObjectCountRepo`, `DebugImageWriter`). Every port has a fake or in-memory implementation, so:

- **Use cases** are unit-tested with a `Mock` detector and repo: no Flask, no TF Serving, no database (`tests/domain/`).
- **The web layer** is tested with real use cases and fake adapters, injected through `create_app(detectors=..., count_repo=...)`.
- **Each adapter** is tested against the real technology it wraps, at the integration level.

In a layered design where the service calls the database and the model directly, most tests would need a real database or heavy patching. Here the boundary is explicit, so each test level replaces exactly the parts it doesn't care about.

## 4. Test doubles

Gerard Meszaros' vocabulary (*xUnit Test Patterns*), with where each is used here:

| Double | What it is | Here |
|---|---|---|
| **Fake** | A working, simplified implementation | `FakeObjectDetector`, `CountInMemoryRepo`, the stub TF Serving HTTP server |
| **Stub** | Returns canned answers | `Mock(return_value=...)` for `requests.post` in `test_object_detector.py`; the recorded TF Serving response |
| **Mock** | Records calls so the test can verify them | the debug image writer in `test_actions.py` (called with all and with valid predictions) |
| **Dummy** | Passed only to fill a parameter | `image=None` in the domain tests |

Two rules keep doubles honest:

1. **Every double must be checked against the real thing somewhere.** `CountInMemoryRepo` passes the same contract suite as PostgreSQL and MongoDB; the stub TF Serving replays the real TF Serving response format, and the e2e job runs the real TF Serving. A fake that drifts from reality makes tests pass for a system that doesn't exist.
2. **Don't mock what you don't own, at the integration level.** Patching `requests.post` is fine for a unit test of the adapter's mapping logic, but it can't prove the HTTP request is right. That's why there's also a test against a real HTTP server.

## 5. Contract tests

Two kinds:

- **Adapter contract** (`tests/adapters/test_count_repo_contract.py`). One suite, run against every `ObjectCountRepo` implementation. If they all pass, any of them can replace another (the Liskov substitution principle, tested). It found two real bugs when it was introduced: the in-memory repo returned `None` for unknown classes, and the Mongo repo returned everything for an empty list.
- **API contract** (`tests/entrypoints/test_openapi.py`). For every path and status code documented in `docs/openapi.yaml`, a test makes the app produce that response and validates it against the spec with `openapi-core`. Two meta-tests fail if a documented status has no test, or if the routes and the spec's paths differ. A negative test checks that the validator really rejects a wrong body (testing the test).

The next step for an API with several consumers would be **consumer-driven contracts** (e.g. Pact), where each client publishes what it relies on and the provider's CI checks it.

## 6. Integration tests

An integration test proves that our code works with a real dependency: SQL that PostgreSQL accepts, documents MongoDB stores, HTTP requests TF Serving understands.

**Real databases, not substitutes.** SQLite instead of PostgreSQL would miss exactly what matters: `INSERT ... ON CONFLICT DO UPDATE`, `ANY(%s)`, transaction isolation, connection pooling. The tests use [Testcontainers](https://testcontainers.com/): each test session starts a throwaway `postgres:16-alpine` and `mongo:7.0` container, so tests are isolated from each other and from developers' databases, and CI and laptops run the same thing. `TEST_POSTGRES_DSN` / `TEST_MONGO_HOST` point them at an existing server instead (used on the development machine, which has no Docker).

**Isolation.** Each test starts from an empty store (`TRUNCATE`, `DROP TABLE` or `drop_database`), so tests don't depend on order.

**Concurrency.** Two tests send 20 concurrent updates, through the repository and through the HTTP API, and check that no update is lost. Concurrency bugs don't show up in single-threaded unit tests. The API-level test found one: on a fresh database, concurrent first requests ran `CREATE TABLE IF NOT EXISTS` at the same time, and PostgreSQL rejected one with a unique-constraint violation on `pg_type`, so a request returned 500 (in 3 of 5 runs). The fix takes a transaction-level advisory lock around schema creation, and `test_concurrent_first_use_creates_the_schema_once` reproduces the race (failing in 4 of 5 runs without the fix).

**TF Serving without Docker.** `tests/integration/test_tf_serving_http.py` runs the app in prod mode (real composition root, factory, label maps, version pinning and HTTP client) against an in-process HTTP server that replays a recorded TF Serving response, including its quirks (float class ids, arrays padded beyond `num_detections`). It covers what a mocked `requests.post` can't: the URL, the JSON payload as sent over the wire (a uint8 `[1, h, w, 3]` batch for RGB, RGBA, greyscale and palette images), HTTP errors, malformed bodies, timeouts and a server that's down. These run in the default suite because they need nothing but Python.

| File | Real | Marker |
|---|---|---|
| `tests/adapters/test_count_repo_contract.py`, `test_count_repo_postgres.py` | PostgreSQL, MongoDB | `integration` |
| `tests/integration/test_api_with_databases.py` | Flask app + PostgreSQL / MongoDB: persistence across restarts, reads don't write, concurrent requests | `integration` |
| `tests/integration/test_tf_serving_http.py` | Flask app in prod mode + HTTP to a stub TF Serving (predict and model status, for readiness) | none (runs everywhere) |
| `tests/scripts/test_model_registry.py` | MLflow registry (SQLite) | `models` |

## 7. End-to-end tests

An e2e test treats the system as a black box and uses it the way a client does. It's the only level that can catch problems in what the lower levels assume: a Docker image missing a file, a wrong port or environment variable in Compose, TF Serving failing to load a model, a payload the real model rejects.

`tests/e2e/test_e2e.py` runs against the whole stack started by `docker compose --profile app up`:

- the app **container** (the image that would be deployed), with gunicorn;
- **TF Serving with both real models**, pulled from the MLflow registry by `make models`;
- MongoDB or PostgreSQL.

Setup waits until TF Serving reports every pulled version as `AVAILABLE`, so the tests don't race the model loading. The tests check that:

- `GET /models` serves exactly the versions in `models.lock.json`;
- the default model finds the cat in `cat.jpg` and the person in `boy.jpg`; scores are sorted and above the threshold; boxes are inside the image;
- `acme_shelf_detector` is really a different model (different predictions for the same image);
- RGBA and greyscale PNGs are detected (the M4 decoding fix, on the real model);
- counting adds to the persisted totals, and with `E2E_COUNT_REPO` the test also reads the database directly to confirm the API and the store agree;
- `/object-predictions` doesn't change the totals; invalid input returns problem+json; `/docs` and `/openapi.yaml` are served;
- **every response is validated against `docs/openapi.yaml`**, so the contract holds on the deployed image, not only in the test client.

CI runs the suite twice: once with counts in MongoDB, then again after switching the app container to PostgreSQL. Then it publishes a second version of `acme_shelf_detector`, makes it the candidate and runs `tests/e2e/test_release.py` twice more: with `RELEASE_MODE=shadow` (the client gets the champion, the candidate's calls and the comparison show up in the metrics) and with `RELEASE_MODE=canary` at 100% (the candidate answers; `release_check` runs real PromQL against Prometheus). Release tests carry a `release_mode(<mode>)` marker and are deselected (not skipped) unless `E2E_RELEASE_MODE` matches, so the other passes stay skip-free.

**Determinism with ML models.** Model outputs change between model versions and can differ slightly between CPUs, so the e2e tests assert **properties** (the expected class is present, scores are in range and sorted, boxes are valid) rather than exact scores. Exact-value ("golden") tests belong to model evaluation, with tolerances, not to API tests.

## 8. What runs where

| Command | Runs | Needs | Time |
|---|---|---|---|
| `make test` (also the pre-push hook) | unit, component/API, contract, stub TF Serving integration: 326 tests | Python only | ~15 s |
| `make coverage` | the same, with a coverage report; fails under 90% | Python only | ~9 s |
| `make test-integration` | real PostgreSQL and MongoDB: 39 tests | Docker (or `TEST_*` servers) | ~1 min |
| `make test-models` | model registry scripts against a throwaway MLflow registry: 11 tests | `make setup-models` | ~10 s |
| `make e2e` | the stack in Docker, then 20 e2e tests (CI adds 4 release tests in shadow and canary mode) | Docker, `make models` | minutes |

Every pull request runs all of them in CI ([`ci.yml`](../.github/workflows/ci.yml)), in parallel jobs: `test` (with coverage), `integration`, `models`, `e2e`, plus `lint`, `security` and `docker`. The `integration` and `e2e` jobs **fail if any test is skipped**: on CI, Docker is available, so a skip means something is broken, not optional.

Pytest markers keep the slow levels out of the default run: `integration`, `models` and `e2e` (see `pyproject.toml`).

## 9. Coverage

`make coverage` measures line coverage of `counter/`: about **96%** from the fast suite alone (the PostgreSQL purge and Mongo index code run only in integration tests), and CI fails below 90%. Code that can't be meaningfully tested in-process (abstract port methods, `if __name__ == "__main__":`) is excluded in `pyproject.toml`.

Coverage shows what the tests **execute**, not what they **check**: a test with no assertions still adds coverage. It's useful to find untested code, not as a quality score. Mutation testing (e.g. `mutmut`) measures the stronger property, whether tests fail when the code is changed; it's a possible next step.

## 10. Deliberately not tested here

- **Model quality** (precision and recall on a labelled data set). That's ML evaluation: it belongs in the training and promotion pipeline (e.g. a gate before `make promote-model`), not in API tests.
- **Load and performance** (requests per second, latency under load). Worth doing with Locust or k6 before production, against a production-like environment.
- **The Werkzeug dev server and gunicorn internals.** Third-party code; only our configuration of them is tested (the e2e tests run the real gunicorn container).

## 11. Inventory

| Level | Files | Tests | Tools |
|---|---|---|---|
| Unit: domain | `tests/domain/` (incl. the threshold business rule, checked before the detector) | 21 | pytest, `unittest.mock` |
| Unit: drift monitoring and evaluation | `tests/monitoring/` (PSI, feature binning, prediction-drift scenarios such as a model losing confidence, input-drift scenarios such as a new camera or greyscale uploads, baselines incl. old ones, cached monitor, Prometheus collector; evaluation metrics, quality-gate decisions, model card; canary verdicts and release info) | 44 | pytest, synthetic prediction records |
| Unit / component: adapters | `tests/adapters/test_object_detector.py`, `test_models.py`, `test_debug_image_writer.py`, `test_count_repo_mongo.py`, repo-down tests in `test_count_repo_postgres.py`, `test_prediction_log.py` (in-memory, background writer: queue full, store down), `test_image_stats.py`, `test_shadow_detector.py` (champion answers, class agreement, failing candidate, pool full) | 63 | pytest, `Mock`, Pillow, `caplog` |
| Component: config, logging, metrics and CLI | `tests/test_config.py`, `tests/test_logging_config.py`, `tests/test_metrics.py` (detector decorator incl. prediction logging, multiprocess metrics, gunicorn hooks), `tests/entrypoints/test_cli.py`, `tests/entrypoints/test_drift_cli.py`, `test_routing.py` (canary share, fallback), `test_release_check.py` (against a stub Prometheus, PromQL injection rejected) | 67 | pytest `monkeypatch`, `capsys`, `runpy`, `prometheus_client` registry, stub HTTP server |
| Component: API | `tests/entrypoints/test_webapp.py` (incl. shadow and canary releases) | 60 | Flask test client, `caplog` (startup line, 503 cause, 500 traceback) |
| Contract: API | `tests/entrypoints/test_openapi.py` (incl. responses during a release) | 29 | `openapi-core`, `openapi-spec-validator` |
| Contract + integration: repositories | `tests/adapters/test_count_repo_contract.py` (memory, PostgreSQL, MongoDB), integration tests in `test_count_repo_postgres.py`, the PostgreSQL prediction log (incl. the migration of an older table), database tuning (fillfactor, index use, BRIN index, retention purge and its interval; Mongo unique index, concurrent first counts, existing duplicates) | 33 (26 need Docker) | Testcontainers, psycopg, pymongo |
| Integration: API + databases | `tests/integration/test_api_with_databases.py` | 12 | Testcontainers |
| Integration: API + TF Serving over HTTP | `tests/integration/test_tf_serving_http.py` | 15 | stub HTTP server, recorded response |
| Integration: model registry | `tests/scripts/test_model_registry.py` (incl. `baseline` and `evaluate` against the stub TF Serving; quality gate, `--force`, candidate serving and its lock with MLflow, `publish --model`) | 21 (11 need MLflow) | MLflow, stub TF Serving |
| Demo data | `tests/scripts/test_demo_data.py` (every feature's status per scenario, repeatable generation, served versions from the locks, drift monitor after seeding, request mix against a running app, `--demo` required, unreachable app; integration: `main` against PostgreSQL with `--reset`, then the drift CLI) | 11 (1 needs Docker) | synthetic records, werkzeug server, psycopg |
| End-to-end | `tests/e2e/test_e2e.py`, `tests/e2e/test_monitoring.py` (Prometheus targets, metrics arrive, dashboard queries valid, alert rules loaded, Grafana provisioned; predictions logged in PostgreSQL and drift reported against the CI-computed baseline), `tests/e2e/test_release.py` (shadow and canary, run in their own CI passes) | 24 | Docker Compose, requests, `openapi-core` |
| **Total** | | **400** | |
