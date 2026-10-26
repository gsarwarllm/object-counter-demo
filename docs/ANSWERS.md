# Answers to the written tasks

This file answers the written parts of the assignment (`Task.md`):

- [Task 3: Code review and proposed improvements](#task-3-code-review-and-proposed-improvements) (with Task 4: which improvements are implemented)
- Task 5 (multiple internal models) and Task 6b (multiple deep-learning frameworks): to be added

## Task 3: Code review and proposed improvements

> Review the rest of the source code and propose some improvements that you would make in the code, the setup instructions, the tests, ...

I reviewed the original code (commit `1095f74`, before any of my changes) and list each finding with the problem, its impact and the fix. Task 4 asks to implement at least one; the **Status** column links each implemented item to the pull request and files that implement it.

**Status:** ✅ implemented · 🟡 partly implemented · 📋 proposed (the ID in brackets is the plan item that will implement it; "not planned" means proposal only)

| Area | Findings | ✅ | 🟡 | 📋 |
|---|---|---|---|---|
| [API and validation](#31-api-and-validation) | 5 | 5 | 0 | 0 |
| [Architecture and domain code](#32-architecture-and-domain-code) | 6 | 3 | 0 | 3 |
| [Adapters](#33-adapters-tf-serving-and-mongodb) | 6 | 5 | 0 | 1 |
| [Setup and documentation](#34-setup-and-documentation) | 7 | 5 | 0 | 2 |
| [Tests](#35-tests) | 5 | 4 | 0 | 1 |
| [CI, security and dependencies](#36-ci-security-and-dependencies) | 4 | 4 | 0 | 0 |
| **Total** | **33** | **26** | **0** | **7** |

### 3.1 API and validation

| ID | Problem | Impact | Proposed fix | Status |
|---|---|---|---|---|
| R1 | `/object-count` converts the threshold with a bare `float(...)`. | `threshold=abc` returns a 500 HTML error page; a client error looks like a server crash. | Parse and validate in one function; return 400 problem+json naming the field. | ✅ [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11): both endpoints use `parse_image_request` ([`schemas.py`](../counter/entrypoints/schemas.py)); first done for `/object-predictions` in PR #3 |
| R2 | The threshold range isn't checked. | `threshold=5` or `-1` is accepted and silently returns nothing or everything. | Reject values outside `[0, 1]` with 400. | ✅ [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11) ([`schemas.py`](../counter/entrypoints/schemas.py)) |
| R3 | A missing `file` field raises `KeyError` in `request.files["file"]`. | Flask returns an HTML 400 page, not JSON; API clients can't parse it. | Check for the field; return 400 problem+json. Register JSON error handlers for every status. | ✅ [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11): problem+json for every status, including 404/405 and 500 ([`webapp.py`](../counter/entrypoints/webapp.py)) |
| R4 | Non-image uploads reach the detector. | Pillow raises inside the adapter → 500. | Decode once at the edge; return 400 "Invalid image". | ✅ [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11): 400 "Invalid image" on both endpoints |
| R5 | No upload size limit. | A client can send arbitrarily large bodies; the image is read fully into memory. | Set `MAX_CONTENT_LENGTH` (10 MB) and return 413 problem+json. | ✅ [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11): `MAX_UPLOAD_BYTES` (default 10 MB) → 413 problem+json |

### 3.2 Architecture and domain code

| ID | Problem | Impact | Proposed fix | Status |
|---|---|---|---|---|
| R6 | The domain layer imports Pillow and `counter.debug` and writes JPEGs (`actions._debug_image`) whenever Python runs without `-O`. | Breaks the hexagonal rule that the domain has no I/O; every request writes files into the working directory in dev, and fails if it's read-only. | Move debug drawing to an adapter injected into the actions (`debug_image_writer` or `None`), enabled by a `DEBUG_IMAGES` flag. | ✅ [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11): `DebugImageWriter` port ([`ports.py`](../counter/domain/ports.py)) and [`FileDebugImageWriter`](../counter/adapters/debug_image_writer.py), enabled by `DEBUG_IMAGES=1`; the domain no longer imports Pillow |
| R7 | `config.py` picks factories by string with `globals()[f"{ENV}_..."]`. | An unknown `ENV` fails with a bare `KeyError`; the indirection hides which factories exist. | An explicit registry dict and a clear error message. | ✅ `COUNT_REPOS` registry ([PR #9](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/9)) and `OBJECT_DETECTORS` registry with a clear error for an unknown `ENV` ([PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11), [`config.py`](../counter/config.py)) |
| R8 | `create_app()` reads `ENV` itself to build its dependencies. | `ENV=prod pytest` fails without live services; tests can't inject fakes. | Let `create_app(count_action=..., detect_action=...)` accept dependencies, defaulting to config. | ✅ [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11): `create_app(count_action=..., detect_action=...)`; tests inject failing detectors |
| R9 | `count()` uses `functools.reduce` with a module-private helper. | Harder to read than needed. | `collections.Counter(p.class_name for p in predictions)`. | 📋 not planned (small cleanup) |
| R10 | Type hints are missing on the public use-case methods (`execute(self, image, threshold)`), and nothing checks them. | Interface mistakes surface only at runtime. | Add hints (`BinaryIO`, `float`) and run `mypy` in CI. | 📋 not planned |
| R11 | `/object-count` updates the totals and then reads them in two separate calls. | Under concurrent requests, the `total_objects` returned can include other requests' counts. The stored totals are still correct. | Document it, or return the totals from the same transaction (Postgres `RETURNING`). | 📋 not planned (acceptable for running totals) |

### 3.3 Adapters (TF Serving and MongoDB)

| ID | Problem | Impact | Proposed fix | Status |
|---|---|---|---|---|
| R12 | `TFSObjectDetector` decodes images with `np.array(image.getdata()).reshape((h, w, 3))`. | RGBA PNGs and greyscale images crash with a reshape error (500); `getdata()` is also slow. | `Image.open(...).convert("RGB")` and `np.asarray(...)`; raise `InvalidImageError` for undecodable input. | ✅ [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11): any mode converted to RGB; tests for RGB, RGBA, greyscale and palette images ([`test_object_detector.py`](../tests/adapters/test_object_detector.py)) |
| R13 | The TF Serving call had no timeout, no status check and used `print` for logging. | A hung model server blocks a worker forever; HTTP errors become confusing `KeyError`s; logs can't be filtered or shipped. | `timeout`, `raise_for_status()`, wrap failures in `DetectorUnavailableError` → 503, use `logging`. | ✅ Timeout in [PR #6](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/6); `raise_for_status`, `DetectorUnavailableError` → 503 and `logging` in [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11) ([`object_detector.py`](../counter/adapters/object_detector.py)) |
| R14 | `CountMongoDBRepo` creates a new `MongoClient` on every read and write. | A new connection pool per call: slow, and can exhaust connections under load. Mongo errors become 500s. | Create the client once; set `serverSelectionTimeoutMS`; wrap `PyMongoError` in `RepositoryUnavailableError` → 503. | ✅ [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11): one client per repo, `MONGO_TIMEOUT`, `PyMongoError` → 503 ([`count_repo.py`](../counter/adapters/count_repo.py)) |
| R15 | Resource files are opened by CWD-relative paths (`counter/adapters/mscoco_label_map.json`, `counter/resources/arial.ttf`). | The app only works when started from the repo root. | Resolve paths from `Path(__file__).parent`. | ✅ [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11): label map and font resolved from `__file__`; tested from another working directory |
| R16 | Repo adapters disagreed on edge cases: the in-memory repo returned `None` for unknown classes; the Mongo repo returned every class for an empty list. | Callers get different results depending on the configured store. | One contract test suite run against every adapter, and fix the differences. | ✅ [PR #9](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/9): [`tests/adapters/test_count_repo_contract.py`](../tests/adapters/test_count_repo_contract.py), fixes in [`count_repo.py`](../counter/adapters/count_repo.py) |
| R17 | The REST request sends the image as a JSON array of pixel integers, and the label map is a single fixed file loaded in the constructor. | Requests are several MB of JSON per image; adding a second model with other labels needs code changes. | Use TF Serving's gRPC API or a base64 `b64` input signature; inject the label map per model (needed for Task 5). | 📋 not planned (gRPC); label map injection with Task 5 |

### 3.4 Setup and documentation

| ID | Problem | Impact | Proposed fix | Status |
|---|---|---|---|---|
| R18 | The README says "Python >= 3.10" and pins nothing; `numpy==1.26.4` doesn't install on Python 3.13+. | Setup fails on current Python versions. | Pin Python 3.12 (`.python-version`, `requires-python`) and create the venv with uv. | ✅ [PR #8](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/8): [`pyproject.toml`](../pyproject.toml), [`.python-version`](../.python-version), `make setup` |
| R19 | Setup is about ten manual steps (model download, two `docker run`s, venv, `PYTHONPATH`). | Slow and error-prone to reproduce; the evaluation asks for automation. | `Makefile` targets, `docker-compose.yml` with health checks, a model download script, pytest `pythonpath` config. | ✅ PR #8: [`Makefile`](../Makefile), [`docker-compose.yml`](../docker-compose.yml), [`scripts/download_model.sh`](../scripts/download_model.sh) |
| R20 | `tmp/model/model_config.config` serves a model called `rfcn` that the setup never downloads. | Using the config file with TF Serving fails to load any model. | Point it at `ssd_mobilenet_v2`, and have compose use it. | ✅ PR #8: [`model_config.config`](../tmp/model/model_config.config) |
| R21 | Runtime and test/tool dependencies are mixed in one file. | The production image installs pytest. | `requirements.txt` (runtime) and `requirements-dev.txt` (tools). | ✅ [PR #6](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/6) and PR #8 |
| R22 | Configuration via env vars is undocumented. | Users have to read the code to find `TFS_HOST`, `MONGO_DB`, ... | `.env.example` and a README table of every variable with its default. | ✅ PR #8 and PR #9: [`.env.example`](../.env.example), [`README.md`](../README.md#configuration) |
| R23 | Only direct dependencies are pinned. | Transitive packages can change between installs, so builds aren't fully reproducible. | Generate a lock file (`uv pip compile` → `requirements.lock`). | 📋 not planned |
| R24 | `.vscode/launch.json` hard-codes `ENV=prod`. | Debugging in VS Code fails unless TF Serving and Mongo are running. | Add a dev configuration and make it the first entry. | 📋 not planned |

### 3.5 Tests

| ID | Problem | Impact | Proposed fix | Status |
|---|---|---|---|---|
| R25 | `test_object_detection` only asserts the body `!= None`. | The test passes even if the response shape is wrong. | Assert the response body (`current_objects`, `total_objects`). | ✅ [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11): `test_object_count` asserts the full body ([`test_webapp.py`](../tests/entrypoints/test_webapp.py)) |
| R26 | The webapp test sends a `model_name` field the app ignores. | Misleading: suggests model selection exists. | Remove it (or implement selection in Task 5). | ✅ [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11): removed |
| R27 | No tests for adapters, persistence or concurrency. | Bugs like R16 went unnoticed. | Integration tests against real databases (testcontainers), including 20 concurrent updates. | ✅ [PR #9](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/9): [`tests/adapters/`](../tests/adapters/), CI `integration` job |
| R28 | No failure-path tests (database down, invalid input). | Error handling can regress silently. | Tests for each error status. | ✅ Every error status is tested on both endpoints: 400, 413, 503 (detector and database), 404/405 and 500 ([PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11)); repo-down tests in PR #9 and [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11) |
| R29 | No end-to-end test of the real stack. | The TF Serving integration (payload format, label mapping) is untested. | e2e tests against the compose stack (`make test-e2e`). | 📋 (M6a). So far CI only smoke-tests the Docker image with the fake detector (PR #8) |

### 3.6 CI, security and dependencies

| ID | Problem | Impact | Proposed fix | Status |
|---|---|---|---|---|
| R30 | No CI. | Nothing stops a broken change from reaching `main`. | GitHub Actions on every PR. | ✅ [PR #2](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/2), extended in PRs #6, #8, #9: jobs `test`, `integration`, `lint`, `security`, `docker` ([`ci.yml`](../.github/workflows/ci.yml)) |
| R31 | No linter or formatter. | Inconsistent style; easy mistakes (unused imports, mutable defaults) go unnoticed. | ruff lint and format checks in CI. | ✅ [PR #6](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/6): 53 findings fixed, config in [`pyproject.toml`](../pyproject.toml) |
| R32 | Pinned dependencies had 15 known vulnerabilities (Pillow 11.3.0, requests, pymongo, Flask, pytest). | Known security issues in image decoding and HTTP handling. | Upgrade, and run `pip-audit` in CI; Dependabot security updates on. | ✅ PR #6 |
| R33 | `webapp.py` ran with `debug=True` on `0.0.0.0`. | The Werkzeug debugger allows remote code execution to anyone who can reach the port. | Bind `127.0.0.1` with the debugger off by default (`HOST`, `FLASK_DEBUG`); serve with gunicorn in Docker; bandit in CI. | ✅ PR #6 ([`webapp.py`](../counter/entrypoints/webapp.py)) and PR #8 ([`Dockerfile`](../Dockerfile)) |

### Task 4: implemented improvements

Task 4 asks to implement at least one proposal. **26 of the 33 are implemented**: R1–R8, R12–R16, R18–R22, R25–R28 and R30–R33. Most code fixes are in [PR #11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11) (plan item M4); setup in PR #8, the PostgreSQL adapter and contract tests in PR #9, CI and security in PRs #2 and #6.

The 7 not implemented are proposals only, or are covered by later plan items:

| ID | Why not (yet) |
|---|---|
| R9 | Small readability cleanup; no behaviour change |
| R10 | Adding `mypy` to CI is worthwhile but out of the assignment's scope |
| R11 | Acceptable for running totals; would need a different repo API |
| R17 | gRPC is a performance change that needs a live TF Serving to measure; per-model label maps come with Task 5 |
| R23 | A lock file is a good next step for fully reproducible builds |
| R24 | Editor configuration, not part of the application |
| R29 | Full end-to-end tests against the compose stack are plan item M6a |
