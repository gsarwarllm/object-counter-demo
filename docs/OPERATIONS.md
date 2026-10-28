# Operations

Running and watching the service: logs, request IDs, metrics, dashboards, drift monitoring and demo data.

## Logs

The app logs to stderr, in one format for its own and library messages. The level comes from `LOG_LEVEL`, the format from `LOG_FORMAT` (`text` or `json`). Every line carries the request ID (`-` outside a request). At `INFO` you get:

- one startup line per process with the models and versions served, `ENV`, the count store and whether debug images are on
- one line per TF Serving call: model, number of detections and time taken (`DEBUG` also logs the URL)
- an `ERROR` line for every `503` (detector or count store down, with the cause) and a traceback for every `500`

Request errors (`400`, `413`) aren't logged; the client gets the details. In Docker, gunicorn also writes one access line per request to stdout, with its duration and request ID. See them with `make logs` or `docker compose logs app`.

## Request IDs

Every response has an `X-Request-ID` header. A caller's own ID is kept if it's at most 128 characters of letters, digits, `.`, `_` and `-`; otherwise the app generates one. Search the logs for it to follow one request.

## Metrics

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

## Dashboards

```bash
make monitoring        # the whole stack plus Prometheus and Grafana
make demo              # the same with synthetic drift data, apart from the real data, plus the MLflow UI and every URL
```

Grafana at [http://localhost:3000](http://localhost:3000) (dashboard "Object Counter": traffic, latency, server errors, detector calls and latency per model version, objects counted per class, prediction and input drift, champion vs candidate during a release); Prometheus at [http://localhost:9090](http://localhost:9090), with alert rules in [`monitoring/alerts.yml`](../monitoring/alerts.yml) (`ModelDrift`, `InputDrift`, `HighServerErrorRate`, `DetectorUnavailable`, `CandidateUnhealthy`; routing them to e-mail or chat needs an Alertmanager). Configuration is in [`monitoring/`](../monitoring/). `make e2e` starts the same profile and checks that Prometheus scrapes the app and TF Serving, loaded the alert rules, and that Grafana loaded the dashboard.

## Model monitoring (drift)

Metrics show whether the service works; drift monitoring shows whether the **model** still behaves as it did when it was released. It needs no labels.

1. **Prediction log.** Every successful model call is logged with its model, version, *every* raw score and class (including those below the caller's threshold: a model losing confidence shows up first as scores sliding toward the threshold), and statistics of the uploaded image: size, colour mode, brightness and contrast (computed on a reduced decode, so they cost little). `PREDICTION_LOG=postgres` (the prod default) writes to the table `prediction_logs` through a background thread, so a slow or unavailable database never delays or fails a request; dropped records are counted in `prediction_log_dropped_total`. `memory` is the dev default; `none` turns it off. Rows older than `PREDICTION_LOG_RETENTION_DAYS` (default 30) are deleted, using a BRIN index on `logged_at` (`sql/005_prediction_logs_retention.sql`); keep it longer than `DRIFT_WINDOW_HOURS`.
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

### Demo data

To show every drift state on the dashboard without real traffic, seed a **local** stack with synthetic data:

```bash
make monitoring                                  # or make up + make run-prod; needs make models
make demo-data RESET=1 REQUESTS=200              # seeds the drift data, then sends 200 requests to the app
make drift                                       # or Grafana after DRIFT_CACHE_SECONDS (5 min)
```

`make demo [REQUESTS=n]` does all of it in one command without touching the real data: the stack runs as its own Compose project (`<folder>-demo`, with its own databases), the synthetic baselines go to `tmp/demo/baselines/` (mounted into the app instead of `tmp/baselines/`), the log is always reset first, drift is recomputed every 30 seconds, and the MLflow UI starts in the background. `make down` stops it and deletes the demo databases. Use `make demo-data` only to seed a stack you started yourself.

For each served version (champion and candidate) it writes a synthetic "healthy" baseline to `BASELINES_DIR` and logs 500 synthetic predictions to `prediction_logs`, spread over the drift window, with fixed seeds, so every run gives the same result:

| Version | Scenario | Statuses |
|---|---|---|
| `ssd_mobilenet_v2` | a night camera: dark, low-contrast greyscale 1280×720 images; the model loses confidence, finds fewer objects and other classes | `drift` on every feature |
| `acme_shelf_detector` | slightly darker shelves with more bottles and cups | `moderate` for `brightness` and `classes`, `stable` elsewhere |
| any candidate | the same traffic as its baseline | `stable` |

`REQUESTS=n` also sends n real requests (every tenth invalid: bad threshold, not an image, unknown model) to `URL` (default `http://localhost:5000`), which fills the traffic, latency, error and, with `RELEASE_MODE`, the release panels; their images are logged too and can move the statuses a little. `RESET=1` first deletes **every** row of `prediction_logs`. The script refuses to run without `--demo` (the make target passes it). Don't run it against real data: it replaces the baselines in `tmp/baselines/` (`make pull-models` restores the real ones from MLflow).
