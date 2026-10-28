# CI and GitHub automation

Everything that runs by itself on GitHub, what each part checks, and how to run the same check on your machine. Nothing here deploys the app: there is no CD. A change is "released" when its pull request is merged into `main` after every check passed.

| Automation | Where | Runs when |
|---|---|---|
| [CI workflow](#ci-workflow), 7 jobs | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | every pull request (each push to it) and every push to `main` |
| [Dependabot](#dependabot) | repository settings | a dependency gets a security advisory |
| [Pre-push hook](#pre-push-hook) (local) | [`.githooks/pre-push`](../.githooks/pre-push) | before every `git push`, once enabled |
| [Codespaces](#codespaces) | [`.devcontainer/devcontainer.json`](../.devcontainer/devcontainer.json) | someone creates a codespace |

## CI workflow

Seven jobs run in parallel on GitHub's `ubuntu-latest` machines with Python 3.12. A pull request is ready to merge only when all of them are green. The times are typical runs.

| Job | What it does | Why | Time | Same check locally |
|---|---|---|---|---|
| `test` | Installs `requirements-dev.lock`; runs every unit, API, contract and stub-TF-Serving test with coverage; **fails below 90%** | Fast feedback on the code itself; no Docker | ~40 s | `make coverage` |
| `integration` | Starts throwaway PostgreSQL and MongoDB containers (testcontainers) and runs the repository and API tests against them; **fails if any test is skipped** (Docker is there, so a skip means something is broken) | The adapters against real databases, not fakes | ~1 min | `make test-integration` |
| `models` | Runs the model-registry script against a temporary MLflow registry (a dummy model, no downloads) | `download`, `publish`, `pull`, `promote` and the quality gate work | ~1.5 min | `make test-models` |
| `e2e` | The whole system with the real models, see [below](#the-e2e-job) | The only job that runs TF Serving for real | ~4 min | `make e2e E2E_COUNT_REPO=mongo` |
| `lint` | `ruff check`, `ruff format --check`, `mypy` (every function annotated), then regenerates the lock files with `uv==0.13.5` and **fails if they changed** | Style, types, and lock files that match `requirements*.txt` | ~30 s | `make lint typecheck` (and `make lock` after editing requirements) |
| `security` | `bandit` (insecure code patterns) and `pip-audit` on `requirements.lock` and `requirements-models.txt` (known vulnerabilities) | No known-vulnerable dependency or risky code merges | ~40 s | `make security` |
| `docker` | Validates `docker-compose.yml` (every profile: setup, app, monitoring), builds the image, starts it with the fake model and sends smoke requests: count, `/models`, both health checks, `/object-counts`, `/metrics`, a request ID round trip, `/openapi.yaml`, `/docs/` | The image builds and serves | ~20 s | `docker build -t object-counter .` |

`make check` runs `lint`, `typecheck`, `docs` (validates `docs/openapi.yaml`), `security` and `test` together: the jobs that need no Docker.

### The e2e job

What a person would do by hand with [`TESTING-GUIDE.md`](TESTING-GUIDE.md), in one job:

1. Install the dev tools and MLflow; restore the model downloads from the cache (key: the hash of `models/models.json`).
2. Download both models, publish them to a local MLflow registry, pull them for TF Serving (`make install` locally).
3. Start the whole stack: app container, TF Serving, MongoDB, PostgreSQL, Prometheus, Grafana (`make monitoring`).
4. Compute the drift baselines and evaluate both versions with an F1 floor of 0.3 (`make baseline`, `make evaluate`).
5. Run the end-to-end tests with the counts in MongoDB, switch the app to PostgreSQL and run them again.
6. Publish a version 2 of `acme_shelf_detector` (the other model's weights stand in for a retrained model), serve it as the candidate, and run the release tests in shadow mode and in canary mode, including the verdict read from Prometheus.
7. On failure, print the last 200 log lines of every container.

Every pass **fails on a skipped test**. The tests are in [`tests/e2e/`](../tests/e2e/): real detections from both models, counting persisted in each database, invalid requests, readiness, metrics and request IDs, the prediction log and drift, Prometheus scraping and alert rules, Grafana's dashboard, shadow and canary releases. How each test level is designed: [`TESTING.md`](TESTING.md).

### Reading a failed run

1. On the pull request, click **Details** next to the red check; the failing step is expanded.
2. Search the log for `FAILED` (pytest) or `Error` (a tool).
3. For `e2e`, the last step (*Run docker compose ... logs*) shows what the containers printed.
4. Reproduce it with the command in the table above, fix it, push again: the checks re-run on the new commit. **Re-run jobs** on the run page repeats a run without a new commit (for a suspected flaky failure).

## Dependabot

Turned on in the repository settings (*Settings* → *Code security*, see [below](#repository-settings-worth-turning-on)): **Dependabot alerts** (a dependency in the lock files has a known vulnerability) and **Dependabot security updates** (it opens a pull request that bumps that dependency). There is no `dependabot.yml`, so it doesn't open pull requests for ordinary version updates. Its pull requests run the same CI.

## Pre-push hook

[`.githooks/pre-push`](../.githooks/pre-push) runs the fast tests before every `git push` and stops the push if one fails, so a broken commit doesn't reach GitHub. Git doesn't enable hooks from a repository by itself; once per clone:

```bash
git config core.hooksPath .githooks
```

`git push --no-verify` skips it once.

## Codespaces

[`.devcontainer/devcontainer.json`](../.devcontainer/devcontainer.json) describes a ready-made development machine: Ubuntu 24.04 with Docker inside it (Docker-in-Docker, so the compose file's `./tmp` folders work), 2 cores and 8 GB, `make install` run once when it is created, and ports 5000, 3000, 9090, 5001 and 8501 forwarded to the browser. How to use it: [`SETUP.md`](SETUP.md#fastest-github-codespaces-nothing-to-install).

## Secrets

None. The CI workflow downloads the models from public URLs, and the databases are throwaway containers with local passwords.

## Repository settings worth turning on

The repository is public, so GitHub offers these for free. They are settings, not files, so a fork or a new copy starts without them:

| Setting | What it does | Where |
|---|---|---|
| Branch protection (a ruleset for `main`) | Merging into `main` only through a pull request, and only when the CI jobs pass | *Settings* → *Rules* → *Rulesets* |
| Secret scanning and push protection | Finds committed passwords and tokens, and blocks pushes that contain them | *Settings* → *Code security* |
| CodeQL code scanning | Deeper security analysis of the Python code, on every pull request | *Settings* → *Code security* → *Code scanning* |
| Dependabot alerts and security updates | See [Dependabot](#dependabot) | *Settings* → *Code security* |

## How a change gets into `main`

1. A short-lived branch from `main`, named `<type>/<topic>` (e.g. `feat/m1-predictions-endpoint`, `docs/setup-from-scratch`).
2. Commits; the pre-push hook runs the fast tests on every push.
3. A pull request: CI runs; fix and push until everything is green.
4. Merge. The CI workflow runs once more on `main`.
