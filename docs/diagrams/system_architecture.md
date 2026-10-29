# System architecture

The whole system in one picture: clients, the hexagonal core, the adapters, the infrastructure the stack runs on, and the setup-time model pipeline. GitHub renders the Mermaid source below; elsewhere, paste it into [mermaid.live](https://mermaid.live).

```mermaid
flowchart LR
    %% ---------- Clients ----------
    subgraph Clients["Clients"]
        HTTP["HTTP client<br/>curl / Swagger UI"]
        CLIUser["CLI user"]
        Ops["Operator<br/>make drift / canary-check"]
    end

    %% ---------- Driving adapters ----------
    subgraph Driving["Driving adapters (counter/entrypoints)"]
        Web["Flask app (webapp.py)<br/>under gunicorn<br/>POST /object-count<br/>POST /object-predictions<br/>GET /object-counts, /models<br/>GET /health, /health/ready<br/>GET /metrics, /openapi.yaml, /docs"]
        Schemas["schemas.py<br/>parse_image_request<br/>format checks: file, JPEG/PNG,<br/>10 MB, threshold, model_name"]
        CLI["main.py (CLI)"]
        DriftCLI["drift.py / release_check.py"]
        Routing["routing.py<br/>ModelRoutes (canary)"]
    end

    Config["config.py<br/>composition root<br/>ENV, COUNT_REPO, PREDICTION_LOG,<br/>RELEASE_MODE, DEBUG_IMAGES"]

    %% ---------- Domain core ----------
    subgraph Core["Domain core (counter/domain), no I/O"]
        Actions["actions.py<br/>CountDetectedObjects<br/>DetectObjects<br/>ReadObjectCounts<br/>check_threshold"]
        Pure["predictions.py<br/>over_threshold / sort_by_score / count"]
        Models["models.py<br/>Prediction, Box, CountResponse"]
        Ports{{"ports.py<br/>ObjectDetector<br/>ObjectCountRepo<br/>DebugImageWriter"}}
        Actions --> Pure
        Actions --> Models
        Actions --> Ports
    end

    %% ---------- Driven adapters ----------
    subgraph Driven["Driven adapters (counter/adapters)"]
        Registry["DetectorRegistry<br/>one ServedModel per model<br/>+ optional Candidate"]
        Instr["InstrumentedDetector<br/>latency/outcome metrics<br/>+ prediction log"]
        Shadow["ShadowDetector<br/>(shadow mode)"]
        TFS["TFSObjectDetector<br/>REST, pinned version,<br/>label map"]
        Fake["FakeObjectDetector<br/>(ENV=dev)"]
        Repos["Count repos<br/>InMemory / MongoDB / Postgres"]
        PLog["PredictionLog<br/>InMemory / Background to Postgres"]
        Debug["FileDebugImageWriter<br/>tmp/debug"]
    end

    %% ---------- Monitoring code ----------
    subgraph Mon["counter/monitoring"]
        Drift["DriftMonitor + DriftCollector<br/>PSI: scores, detections,<br/>classes, image stats"]
        Release["ReleaseCollector<br/>model_release_info"]
    end

    %% ---------- Infrastructure (Docker Compose) ----------
    subgraph Infra["Infrastructure (Docker Compose)"]
        TFServing[("TF Serving :8501<br/>ssd_mobilenet_v2<br/>acme_shelf_detector")]
        Mongo[("MongoDB<br/>collection counter")]
        PG[("PostgreSQL 16<br/>object_counts<br/>prediction_logs")]
        Prom["Prometheus :9090<br/>alert rules"]
        Graf["Grafana :3000<br/>dashboard Object Counter"]
    end

    %% ---------- Setup-time model pipeline ----------
    subgraph Setup["Setup time (not imported by the app)"]
        Script["scripts/model_registry.py<br/>download / publish / evaluate /<br/>promote / pull / baseline"]
        MLflow[("MLflow registry<br/>tmp/mlflow")]
        Files["tmp/model/<br/>models.lock.json<br/>candidates.lock.json<br/>model_config.config<br/>tmp/baselines/"]
        Manifest["models/models.json<br/>+ label maps"]
    end

    %% ---------- Flows ----------
    HTTP --> Web
    CLIUser --> CLI
    Ops --> DriftCLI
    Web --> Schemas --> Actions
    CLI --> Actions
    Web --> Routing --> Registry

    Config -. builds .-> Web
    Config -. builds .-> Registry
    Config -. builds .-> Repos
    Config -. builds .-> PLog

    Ports -. implemented by .-> Instr
    Ports -. implemented by .-> Repos
    Ports -. implemented by .-> Debug

    Registry --> Instr
    Instr --> Shadow
    Instr --> TFS
    Instr --> Fake
    Shadow --> TFS
    Instr --> PLog

    TFS -->|HTTP predict / status| TFServing
    Repos --> Mongo
    Repos --> PG
    PLog --> PG

    Drift --> PLog
    Drift --> Files
    Web -->|/metrics| Drift
    Web --> Release
    DriftCLI --> Drift
    DriftCLI -->|PromQL| Prom

    Prom -->|scrape /metrics| Web
    Prom -->|scrape| TFServing
    Graf --> Prom

    Manifest --> Config
    Script --> MLflow
    Script -->|pull| Files
    Script -->|baseline| TFServing
    Files -->|mounted| TFServing
    Files -->|pinned versions| Config
```

## How to read it

- **Left to right:** clients, driving adapters, domain core, driven adapters, infrastructure.
- **The core owns the ports.** Adapters implement them (dotted "implemented by" edges); `counter/config.py`, the composition root, builds every concrete piece from environment variables.
- **Dev vs prod:** `ENV=dev` uses `FakeObjectDetector` and the in-memory count repo and prediction log, so no Docker is needed. `ENV=prod` uses TF Serving and MongoDB or PostgreSQL.
- **Setup time vs runtime:** the MLflow registry and `scripts/model_registry.py` run only at setup time. At runtime the app reads only the pulled files: pinned versions in `models.lock.json` and the drift baselines.

See [ARCHITECTURE.md](../ARCHITECTURE.md) for the layers in detail and [OPERATIONS.md](../OPERATIONS.md) for metrics, dashboards and drift.
