# Demo URLs

Every page to open while trying the app, on your own machine or in a GitHub codespace. `make urls` prints the same list with the exact addresses for wherever it runs.

## Where the addresses come from

| | Local machine | GitHub codespace |
|---|---|---|
| Address of port `P` | `http://localhost:P` | `https://<codespace-name>-P.app.github.dev` (`make urls` fills in the name; also in the **Ports** tab) |
| Who can open it | only this machine | **private** by default: only you, signed in to GitHub. For a panel or a colleague: **Ports** tab → right-click the port → *Port Visibility* → **Public** (anyone with the link, no login). Set it back to *Private* afterwards. |
| How long it works | while the containers run | while the codespace runs: it stops after the idle timeout (30 minutes by default, up to 4 hours in GitHub *Settings* → *Codespaces*); the address is the same after a restart |

Start the app first: `make start` (API and models), `make monitoring` (also Grafana and Prometheus) or `make demo` (all of that plus synthetic drift data, kept apart from the real data, and the MLflow UI; about 5.5 GB RAM; `make down` stops it all). On Windows without WSL: [PowerShell, Docker only](SETUP.md#windows-powershell-docker-only-no-wsl-terminal-no-make).

## The pages

The paths are the same in both places: replace `localhost:P` with the codespace address of port `P`.

| Page | Local URL | What you see | Needs |
|---|---|---|---|
| **Swagger UI** | [localhost:5000/docs/](http://localhost:5000/docs/) | Every endpoint with *Try it out*: upload an image to `POST /object-count` or `/object-predictions`, pick the threshold and the model | `make start` |
| Readiness | [localhost:5000/health/ready](http://localhost:5000/health/ready) | `"status":"ok"` when the database and both models are ready | `make start` |
| Models | [localhost:5000/models](http://localhost:5000/models) | The served models, their versions and the default; a running shadow or canary release | `make start` |
| Totals | [localhost:5000/object-counts](http://localhost:5000/object-counts) | Objects counted so far, per class (`?object_class=cat` filters) | `make start` |
| API contract | [localhost:5000/openapi.yaml](http://localhost:5000/openapi.yaml) | The OpenAPI 3 specification the tests check the API against | `make start` |
| App metrics | [localhost:5000/metrics](http://localhost:5000/metrics) | Prometheus metrics: requests, latency, detector calls, objects counted, drift | `make start` |
| **Grafana dashboard** | [localhost:3000/d/object-counter](http://localhost:3000/d/object-counter) | 11 panels: traffic, latency, errors, detector calls per model version, objects per class, prediction and input drift, releases (no login to view; `admin`/`admin` to edit) | `make monitoring` or `make demo` |
| Prometheus targets | [localhost:9090/targets](http://localhost:9090/targets) | The app and TF Serving, both *UP* | `make monitoring` or `make demo` |
| Prometheus alerts | [localhost:9090/alerts](http://localhost:9090/alerts) | The 5 alert rules: `ModelDrift`, `InputDrift`, `HighServerErrorRate`, `DetectorUnavailable`, `CandidateUnhealthy` | `make monitoring` or `make demo` |
| TF Serving, default model | [localhost:8501/v1/models/ssd_mobilenet_v2](http://localhost:8501/v1/models/ssd_mobilenet_v2) | The model version TF Serving loaded and its state (`AVAILABLE`) | `make start` |
| TF Serving, second model | [localhost:8501/v1/models/acme_shelf_detector](http://localhost:8501/v1/models/acme_shelf_detector) | The same for the second model | `make start` |
| MLflow registry | [127.0.0.1:5001](http://127.0.0.1:5001) | Registered models, versions, aliases (`champion`), evaluation scores and baselines | `make mlflow-ui` in its own terminal, or `make demo` (about 20 seconds to start) |

The app's root address (`localhost:5000/` alone) answers `404`: the API has no home page. Open `/docs/` instead.

## A 5-minute demo, in order

1. [Swagger UI](http://localhost:5000/docs/) → **POST /object-count** → *Try it out* → choose an image (e.g. `resources/images/cat.jpg`) → *Execute*: the objects found and the running totals.
2. The same with `model_name` = `acme_shelf_detector`: another model answers (`"model"` in the response).
3. [Totals](http://localhost:5000/object-counts): what has been counted so far.
4. [Grafana](http://localhost:3000/d/object-counter): the requests just sent appear in the traffic and detector panels within about 30 seconds (Prometheus scrapes every 15 s, the dashboard refreshes every 10 s).
5. [Readiness](http://localhost:5000/health/ready): what a load balancer asks before sending traffic.

Send one request to each model shortly before a demo: the first call after a start takes about 5 seconds.

More to try, step by step: [`TESTING-GUIDE.md`](TESTING-GUIDE.md).
