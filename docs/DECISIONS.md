# Design decisions

The main choices behind this project, in one place: what was decided, what else was considered,
and why. The reasoning in more detail is in [`plan.md`](../plan.md) (assumptions A1–A24 in
section 3, and each task's section) and in [`ANSWERS.md`](ANSWERS.md).

## Architecture

**1. Hexagonal layout: the domain owns the ports.**
The use cases (`counter/domain/actions.py`) talk to the outside world only through interfaces
defined in `counter/domain/ports.py` (`ObjectDetector`, `ObjectCountRepo`, `PredictionLog`,
`DebugImageWriter`); adapters implement them. The domain has no I/O and imports no framework,
database driver or Pillow.
*Why:* storage, models and the web framework can change without touching business logic, and
the core is tested with simple fakes. This is what the assignment set out to demonstrate.
*Trade-off:* more files and indirection than a single Flask module would need.

**2. One composition root, adapters chosen by configuration.**
`counter/config.py` builds every adapter from environment variables (`ENV`, `COUNT_REPO`,
`PREDICTION_LOG`, ...). `ENV=dev` uses a fake detector and in-memory counts.
*Alternative:* choosing adapters inside the routes or the domain.
*Why:* one place decides what runs; the app starts and its tests run with no TF Serving or
database, and `create_app()` accepts injected adapters for tests.

**3. Format checks in the adapters, business rules in the core.**
The web layer (`schemas.py`) and the CLI check that input is readable: a number, a JPEG or PNG
file, under 10 MB. The threshold range `[0, 1]` is checked in the domain (`check_threshold`),
before the detector is called.
*Why:* a rule enforced in one adapter has to be copied into every other one. Before this
change, the CLI accepted a threshold of 5 and silently counted nothing.

**4. Keep Flask.**
*Alternative:* migrating to FastAPI (outlined in `plan.md` section 8).
*Why:* the architecture is already exercised with several adapters on each side (three count
stores, two detectors, a web app and a CLI). Rewriting working, tested code adds risk without
new behaviour.

## API

**5. `POST /object-predictions` for the predictions endpoint (Task 1).**
It returns `{threshold, count, predictions[]}`, sorted by score, and never writes to the count
store.
*Alternatives:* `GET` with an image body or `?image_url=`, `PUT`, the draft `QUERY` method.
*Why:* the request carries an image. A GET body has no defined meaning and may be dropped,
an image doesn't fit in a URL, fetching a URL server-side is an SSRF risk, and POST multipart
matches `/object-count`. An object rather than a bare array can grow without breaking clients.
*Trade-off:* POST doesn't advertise that the call is safe; the OpenAPI spec says so.

**6. Threshold: inclusive, between 0 and 1, default 0.5.**
*Why:* keeps the original `score >= threshold` behaviour; a threshold is a score, so values
outside `[0, 1]` are errors, not empty results.

**7. Errors as RFC 7807 problem+json with meaningful status codes.**
400 for bad input, 413 for an upload over 10 MB, 503 when the model server or the database is
unavailable, 500 only for real bugs, which are logged with a traceback but never returned.
*Why:* clients can tell their own mistakes from outages and retry only the latter; one
standard format instead of HTML error pages.

**8. Contract first.**
`docs/openapi.yaml` is written by hand and is the source of truth; contract tests validate every
documented path and status against it and fail if a route is missing from the spec.
*Alternative:* generating the spec from code.
*Why:* the API is designed before it is coded, and the documentation can't silently drift.

## Storage

**9. PostgreSQL as the relational adapter, MongoDB kept (Task 2).**
`COUNT_REPO=memory|mongo|postgres` selects the store. Increments use
`INSERT ... ON CONFLICT DO UPDATE`, one transaction per request with rows in a fixed order.
*Alternative:* MySQL (also allowed); an ORM.
*Why:* PostgreSQL's atomic upsert means concurrent requests never lose counts; plain SQL keeps
the adapter small. The same contract tests run against all three stores, so they behave
identically.

**10. Schema created on first use, under a lock.**
Tables are created lazily (`counter/adapters/sql/`) inside a PostgreSQL advisory lock.
*Alternative:* a migration tool (Alembic, Flyway).
*Why:* the app starts even while the database is still down, and a concurrency test found that
two processes creating the table at once fail without the lock. A migration tool is the next
step when the schema starts changing often.

## Models

**11. The model is a request parameter, not an endpoint (Task 5).**
Requests take an optional `model_name`; `GET /models` lists the choices.
*Why:* endpoints describe what the API does, the model is how. An endpoint per model adds
routes with every release and forces clients to change URLs to switch or roll back. A new
endpoint is right only for a different task with a different response.

**12. Pinned model versions, no automatic fallback.**
Production serves exactly the versions in `models.lock.json` and refuses to start without them.
If a model is unavailable, the API returns 503.
*Alternative:* answering with another model.
*Why:* totals are stored; counts from a different model, with other classes and accuracy, would
corrupt them without anyone noticing.

**13. A model registry at setup time only.**
A local MLflow registry stands in for a private one: publish, promote and pull are `make`
targets in a separate environment.
*Why:* MLflow is a large dependency the app never needs at runtime; replacing it only touches
`scripts/model_registry.py`.

**14. One shared count store for all models.**
*Why:* keeps the repository port unchanged. Totals per model would only change the key to
`(model, class)`, a repository change rather than a redesign.

## Monitoring and releases

**15. Drift measured with the Population Stability Index, per model version.**
Every model call is logged with all raw scores and classes and simple image statistics, and
compared with a baseline computed for that exact version. Below 0.1 is stable, 0.1–0.25
moderate, 0.25 or more drift.
*Why:* production has no labels, so accuracy can't be measured directly; PSI is simple,
explainable and works on scores, classes and image properties alike. Drift says the inputs or
outputs changed, not that the model is wrong.

**16. The prediction log never slows down or fails a request.**
Records go to PostgreSQL from a background thread with a bounded queue; dropped records are
counted in a metric.
*Why:* monitoring is useful but not worth a failed or slower request.

**17. A quality gate before promotion, on image-level F1.**
`promote` refuses a version that wasn't evaluated, was evaluated on a different set, or scores
more than 0.02 F1 below the current champion; `--force` overrides and tags the version.
*Alternative:* mAP.
*Why:* the evaluation set records which classes appear in each image, not their boxes; mAP would
need box annotations.

**18. Shadow and canary releases, promoted by a person.**
The candidate version either answers a copy of the traffic in the background (shadow) or a share
of real requests (canary). `make canary-check` judges errors, latency and drift from Prometheus,
and `make canary-promote` promotes, still through the quality gate.
*Alternative:* automatic promotion inside the app.
*Why:* the app stays simple and stateless; the decision uses data from all processes, and a
person stays in control of what reaches production.

## Engineering

**19. Reproducible setup.**
Python 3.12 pinned, every dependency locked (`requirements*.lock`), one `make` target per task,
Docker Compose for the services.
*Why:* the assignment asks for a setup that is "automated and smoothly reproducible".

**20. Tests at every level, asserting properties with real models.**
Unit, API, contract, integration (real PostgreSQL and MongoDB, a stub TF Serving) and end-to-end
tests against the Docker stack with the real models, all in CI. End-to-end tests check
properties (the expected class is found, scores are sorted, boxes are valid), not exact scores.
*Why:* scores change between model versions and CPUs; exact values belong to model evaluation.

**21. One repository, changes only through pull requests.**
Short-lived branches, one per item; `main` always passes the seven CI jobs.

## Deliberately not built

| Item | Why |
|---|---|
| Other ML frameworks (Task 6(b)) | The task allows an outline; it's in [`ANSWERS.md`](ANSWERS.md#task-6b-multiple-deep-learning-frameworks-outline) with a diagram |
| FastAPI (O6) | See decision 4 |
| Authentication (O1) | Not part of the assignment; an internal service is usually protected by a gateway in front of it. Designed in two phases in `plan.md` |
| Feedback loop with labels (X7) | Needs labelling and a training pipeline; the models here are pretrained |
