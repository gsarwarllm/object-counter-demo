# Architecture

How the code is organised: hexagonal architecture (ports and adapters), the order to read it in, what dev and prod mode really run, and the two databases.

## Layers

The application is composed of three layers:

- **entrypoints**: Exposes the API and receives the requests. It checks the request format (a number, a JPEG or PNG file, the size limit) and returns the responses; business rules such as the threshold range are checked in the domain.

- **adapters**: Communicates with external services. It is responsible for translating the domain objects to the external services objects and vice-versa.

- **domain**: Business logic. It is responsible for orchestrating the calls to the external services and for applying the business rules.

![Hexagonal architecture: driving adapters (Flask API, CLI; FastAPI planned) call the use cases in the core, which reach storage and models only through ports implemented by driven adapters (in-memory, MongoDB and PostgreSQL repositories, TF Serving detector)](diagrams/hexagonal_architecture.png)

The domain owns the ports (interfaces); adapters on both sides implement or call them, and `counter/config.py` (the composition root) picks the adapters from environment variables. Swapping MongoDB for PostgreSQL, or the fake model for TF Serving, changes no domain code.

For the whole system (adapters, infrastructure, monitoring and the setup-time model pipeline) in one Mermaid diagram, see [System architecture](diagrams/system_architecture.md).

## Read the code in this order

| # | File | What it shows |
|---|---|---|
| 1 | [`counter/domain/ports.py`](../counter/domain/ports.py) | The ports: the interfaces the core owns (`ObjectDetector`, `ObjectCountRepo`, `PredictionLog`, `DebugImageWriter`) |
| 2 | [`counter/domain/actions.py`](../counter/domain/actions.py) | The use cases (count, predict, read totals) and the threshold rule; no I/O, no framework imports |
| 3 | [`counter/adapters/count_repo.py`](../counter/adapters/count_repo.py), [`object_detector.py`](../counter/adapters/object_detector.py) | Driven adapters: memory, MongoDB and PostgreSQL behind one port; TF Serving and a fake detector behind another |
| 4 | [`counter/config.py`](../counter/config.py) | The composition root: picks the adapters from environment variables (`ENV`, `COUNT_REPO`, ...) |
| 5 | [`counter/entrypoints/webapp.py`](../counter/entrypoints/webapp.py), [`schemas.py`](../counter/entrypoints/schemas.py), [`main.py`](../counter/entrypoints/main.py) | Driving adapters: HTTP and the CLI call the same use cases; errors become RFC 7807 problem+json |
| 6 | [`docs/openapi.yaml`](openapi.yaml) | The API contract, checked by [`tests/entrypoints/test_openapi.py`](../tests/entrypoints/test_openapi.py) |
| 7 | [`tests/adapters/test_count_repo_contract.py`](../tests/adapters/test_count_repo_contract.py) | One test suite that every count repository must pass |

## Dev or prod: what each mode really runs

`ENV` picks the adapters in [`counter/config.py`](../counter/config.py) (the composition root); the domain code is the same in every mode. Dev mode only shows that the HTTP layer and the use cases work: it never runs a model and keeps nothing.

| | Dev: `make run` | Prod on the host: `make start` | All in Docker: `make monitoring` or `make demo` |
|---|---|---|---|
| `ENV` | `dev` | `prod` | `prod` |
| Object detector | `FakeObjectDetector`: returns exactly one `cat` (score 0.999, the same box) **for any image**, so counts, classes and scores say nothing about the picture | TF Serving with the real models | the same |
| Model version in answers | `"version":null`: nothing is pinned | the version pulled by `make pull-models` (`tmp/model/models.lock.json`); the app refuses to start without it | the same |
| Count store | memory (`CountInMemoryRepo`): lost when the app stops | MongoDB (`COUNT_REPO=postgres`: PostgreSQL), kept in Docker volumes | the same |
| Prediction log (input for drift) | memory: lost when the app stops | PostgreSQL table `prediction_logs`, written in the background | the same |
| Drift | no baseline belongs to an unpinned fake model, so no drift result | compared with each version's baseline (`make drift`, `/metrics`) | the same, plus Grafana panels and alerts |
| `/health/ready` | always `ok`: the fake detector and memory are always ready, so it proves nothing | asks TF Serving for each pinned version and pings the database: `503` when one is down | the same; also the container healthcheck |
| Failure handling (`503`) | can't be seen: nothing can fail | stop TF Serving or a database and see `503` and the recovery | the same |
| Shadow and canary releases | ignored: only prod serves candidates | `RELEASE_MODE` on the host app | `RELEASE_MODE` on the app container |
| Web server | Flask's development server, one process | the same | gunicorn with 2 workers (`WEB_CONCURRENCY`), metrics shared between them: the production setup |
| Monitoring | `/metrics` only | `/metrics` only | Prometheus scrapes the app and TF Serving; Grafana dashboard; 5 alert rules |
| Needs | `make setup` only | `make install` and Docker | `make install` and Docker |
| Use it for | writing code, the fast tests, a quick check of the API | real results, both databases, failures, releases | the full system as deployed, dashboards, end-to-end tests |

Each setting can be overridden on its own, e.g. `COUNT_REPO=postgres make run` keeps the fake model but stores the counts in PostgreSQL (with `make up` running).

## Databases

Counts go to MongoDB by default in prod. To use PostgreSQL instead (Task 2):

```bash
COUNT_REPO=postgres make start
```

The table `object_counts` is created on first use (schema in `counter/adapters/sql/001_object_counts.sql`). Increments use `INSERT ... ON CONFLICT DO UPDATE`, so concurrent requests don't lose updates. If the database is down, `/object-count` returns `503` (problem+json) and `/object-predictions` keeps working.

Database tuning, applied automatically on first use:

- **PostgreSQL:** `object_counts` is a handful of rows updated on every request, so its pages keep 20% free space (`fillfactor = 80`, `sql/004_object_counts_fillfactor.sql`). PostgreSQL can then rewrite a row in the same page without touching the primary-key index (a HOT update), and neither the table nor the index bloats.
- **MongoDB:** a unique index on `object_class` (`object_class_unique`) makes lookups by class use an index and stops two concurrent first counts of a class from creating two documents. All increments of one request go in a single `bulk_write`. If older data already holds duplicates, the index can't be built: the app logs an error and keeps counting, and the duplicates have to be merged by hand.
