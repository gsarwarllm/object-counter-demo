# Configuration

Every environment variable, its default and what it changes.

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
| `PREDICTION_LOG_RETENTION_DAYS` | `30` | `postgres` prediction log only: rows older than this are deleted, at most once an hour, in batches of 10 000, by the background writer; `0` keeps everything |
| `BASELINES_DIR` | `tmp/baselines` | Drift baselines, one `<model>/<version>.json` per version |
| `DRIFT_WINDOW_HOURS` | `24` | How much recent traffic is compared with the baseline |
| `DRIFT_MIN_IMAGES` | `30` | Below this many images in the window, no PSI is reported |
| `DRIFT_CACHE_SECONDS` | `300` | How long `/metrics` reuses a drift result |
| `RELEASE_MODE` | `off` | What the app does with each model's candidate version (prod): `off`, `shadow` or `canary` ([releases](MODELS.md#shadow-and-canary-releases)) |
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
