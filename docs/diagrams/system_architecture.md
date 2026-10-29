# System architecture

The system in five views, from the big picture down to the details. GitHub renders the Mermaid source below; elsewhere, paste it into [mermaid.live](https://mermaid.live).

1. [Overview](#1-overview): the layers and how they connect
2. [Request path](#2-request-path): an HTTP request through the hexagonal core
3. [Detection chain](#3-detection-chain): from the core's port to TF Serving
4. [Monitoring](#4-monitoring): metrics, drift and dashboards
5. [Setup-time model pipeline](#5-setup-time-model-pipeline): how models reach TF Serving

## 1. Overview

Each box is a layer; arrows show who calls whom. Dependencies point inward to the domain core, which has no I/O.

```mermaid
flowchart TB
    Clients["<b>Clients</b><br/>HTTP client · CLI user · Operator"]
    Driving["<b>Driving adapters</b><br/>counter/entrypoints<br/>Flask app · CLI · drift / release tools"]
    Core["<b>Domain core</b><br/>counter/domain<br/>actions · models · ports (no I/O)"]
    Driven["<b>Driven adapters</b><br/>counter/adapters<br/>detectors · count repos · prediction log"]
    Infra[("<b>Infrastructure</b><br/>TF Serving · MongoDB · PostgreSQL<br/>Prometheus · Grafana")]
    Config["<b>config.py</b><br/>composition root"]
    Setup["<b>Setup time</b><br/>model_registry.py · MLflow"]

    Clients --> Driving --> Core --> Driven --> Infra
    Config -. builds .-> Driving
    Config -. builds .-> Driven
    Setup -. pulls models and lock files .-> Infra
    Setup -. pinned versions .-> Config

    classDef core fill:#fff3bf,stroke:#e0a800,color:#000
    classDef setup fill:#eeeeee,stroke:#888,color:#000,stroke-dasharray:4 3
    class Core core
    class Setup setup
```

## 2. Request path

A `POST /object-count` request, top to bottom. The core defines the ports; the adapters implement them.

```mermaid
flowchart TB
    HTTP["HTTP client<br/>curl / Swagger UI"]
    CLIUser["CLI user"]

    subgraph Driving["Driving adapters · counter/entrypoints"]
        direction TB
        Web["webapp.py<br/>Flask under gunicorn"]
        Schemas["schemas.py<br/>parse_image_request<br/>JPEG/PNG · 10 MB · threshold · model_name"]
        Routing["routing.py<br/>ModelRoutes (canary)"]
        CLI["main.py"]
    end

    subgraph Core["Domain core · counter/domain"]
        direction TB
        Actions["actions.py<br/>CountDetectedObjects · DetectObjects<br/>ReadObjectCounts · check_threshold"]
        Pure["predictions.py<br/>over_threshold · sort_by_score · count"]
        Models["models.py<br/>Prediction · Box · CountResponse"]
        Ports{{"ports.py<br/>ObjectDetector<br/>ObjectCountRepo<br/>DebugImageWriter"}}
    end

    subgraph Driven["Driven adapters · counter/adapters"]
        direction LR
        Detectors["Detector chain<br/>(see view 3)"]
        Repos["Count repos<br/>InMemory / MongoDB / Postgres"]
        Debug["FileDebugImageWriter<br/>tmp/debug"]
    end

    HTTP --> Web
    CLIUser --> CLI
    Web --> Schemas --> Actions
    Web --> Routing
    CLI --> Actions
    Actions --> Pure
    Actions --> Models
    Actions --> Ports
    Ports -. implemented by .-> Detectors
    Ports -. implemented by .-> Repos
    Ports -. implemented by .-> Debug
    Routing -. picks model .-> Detectors

    classDef core fill:#fff3bf,stroke:#e0a800,color:#000
    class Actions,Pure,Models,Ports core
```

**Endpoints served by `webapp.py`:**

| Method | Path |
| --- | --- |
| POST | `/object-count`, `/object-predictions` |
| GET | `/object-counts`, `/models` |
| GET | `/health`, `/health/ready` |
| GET | `/metrics`, `/openapi.yaml`, `/docs` |

## 3. Detection chain

How an `ObjectDetector` call reaches a model, and what it writes on the way.

```mermaid
flowchart LR
    Routing["routing.py<br/>ModelRoutes"]

    subgraph Adapters["counter/adapters"]
        direction LR
        Registry["DetectorRegistry<br/>one ServedModel per model<br/>+ optional Candidate"]
        Instr["InstrumentedDetector<br/>latency / outcome metrics"]
        Shadow["ShadowDetector<br/>shadow mode"]
        TFS["TFSObjectDetector<br/>REST · pinned version · label map"]
        Fake["FakeObjectDetector<br/>ENV=dev"]
        PLog["PredictionLog<br/>InMemory / background to Postgres"]
    end

    TFServing[("TF Serving :8501<br/>ssd_mobilenet_v2<br/>acme_shelf_detector")]
    PG[("PostgreSQL 16<br/>prediction_logs")]

    Routing --> Registry --> Instr
    Instr -->|prod| TFS
    Instr -->|dev| Fake
    Instr -->|shadow| Shadow --> TFS
    Instr -->|log each prediction| PLog
    TFS -->|HTTP predict / status| TFServing
    PLog --> PG
```

**Storage by environment:**

| | `ENV=dev` | `ENV=prod` |
| --- | --- | --- |
| Detector | `FakeObjectDetector` | `TFSObjectDetector` → TF Serving |
| Count repo | in memory | MongoDB (`counter`) or PostgreSQL (`object_counts`) |
| Prediction log | in memory | PostgreSQL (`prediction_logs`) |
| Docker needed | no | yes |

## 4. Monitoring

Prometheus scrapes the app and TF Serving; drift is computed from the prediction log against the setup-time baselines.

```mermaid
flowchart LR
    Ops["Operator<br/>make drift / canary-check"]

    subgraph App["Object counter app"]
        direction TB
        Web["webapp.py<br/>GET /metrics"]
        Drift["DriftMonitor + DriftCollector<br/>PSI on scores, detections,<br/>classes, image stats"]
        Release["ReleaseCollector<br/>model_release_info"]
        DriftCLI["drift.py / release_check.py"]
    end

    PLog[("Prediction log")]
    Baselines["tmp/baselines/"]
    TFServing[("TF Serving")]
    Prom["Prometheus :9090<br/>alert rules"]
    Graf["Grafana :3000<br/>Object Counter dashboard"]

    Ops --> DriftCLI
    DriftCLI --> Drift
    DriftCLI -->|PromQL| Prom
    Web --> Drift
    Web --> Release
    Drift --> PLog
    Drift --> Baselines
    Prom -->|scrape /metrics| Web
    Prom -->|scrape| TFServing
    Graf --> Prom
```

## 5. Setup-time model pipeline

Runs once before the stack starts; the app never imports this code. At runtime the app reads only the pulled files.

```mermaid
flowchart LR
    Manifest["models/models.json<br/>+ label maps"]
    Script["scripts/model_registry.py<br/>download · publish · evaluate<br/>promote · pull · baseline"]
    MLflow[("MLflow registry<br/>tmp/mlflow")]

    subgraph Files["Pulled files"]
        direction TB
        Model["tmp/model/<br/>models.lock.json<br/>candidates.lock.json<br/>model_config.config"]
        Baselines["tmp/baselines/"]
    end

    TFServing[("TF Serving")]
    Config["config.py"]

    Script <-->|publish / promote / pull| MLflow
    Script -->|pull| Model
    Script -->|baseline| Baselines
    Script -. queries for baselines .-> TFServing
    Model -->|mounted| TFServing
    Model -->|pinned versions| Config
    Manifest --> Config
```

## How to read it

- **The core owns the ports.** Adapters implement them; `counter/config.py`, the composition root, builds every concrete piece from environment variables (`ENV`, `COUNT_REPO`, `PREDICTION_LOG`, `RELEASE_MODE`, `DEBUG_IMAGES`).
- **Dev vs prod:** `ENV=dev` uses `FakeObjectDetector` and the in-memory count repo and prediction log, so no Docker is needed. `ENV=prod` uses TF Serving and MongoDB or PostgreSQL.
- **Setup time vs runtime:** the MLflow registry and `scripts/model_registry.py` run only at setup time. At runtime the app reads only the pulled files: pinned versions in `models.lock.json` and the drift baselines.

See [ARCHITECTURE.md](../ARCHITECTURE.md) for the layers in detail and [OPERATIONS.md](../OPERATIONS.md) for metrics, dashboards and drift.
