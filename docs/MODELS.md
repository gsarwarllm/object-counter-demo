# Models

The two models, the local MLflow registry, releasing and rolling back versions with the quality gate, and shadow and canary releases.

## Registry and versions

The models come from Google's [TensorFlow 1 Object Detection model zoo](https://github.com/tensorflow/models/blob/master/research/object_detection/g3doc/tf1_detection_zoo.md): SSD MobileNet v2 (COCO, the default) and SSDLite MobileNet v2 (COCO), which stands in for an internally trained model. They're listed in [`models/models.json`](../models/models.json).

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
- **Evaluation set:** [`models/evaluation/coco_sample.json`](../models/evaluation/coco_sample.json) labels which COCO classes are visible in each sample image (image-level, no boxes). Three images only demonstrate the gate; use `DATASET=` with a set of hundreds of images like the production traffic. Its fingerprint (labels + images) is stored with each evaluation, so versions are only compared on the same set.
- **Drift baseline for a version:** after `make up`, `make baseline` (optionally `IMAGES=/path/to/validation/images`); `make pull-models` fetches stored baselines with their versions. See [Model monitoring](OPERATIONS.md#model-monitoring-drift).
- **Browsing the registry:** `make mlflow-ui`, then open http://127.0.0.1:5001.
- **Private registry:** set `MLFLOW_TRACKING_URI` to your MLflow server (with its credentials); the same commands work.

In dev (`ENV=dev`), every model in the manifest is served by the fake detector, so model selection works without Docker (see [Dev or prod](ARCHITECTURE.md#dev-or-prod-what-each-mode-really-runs)).

## Shadow and canary releases

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
