"""End-to-end setup: the whole stack must already be running (see `make e2e`).

E2E_BASE_URL     the app, e.g. http://localhost:5000 (tests are skipped when unset)
E2E_TFS_URL      TF Serving REST, to wait until the pulled model versions are loaded
E2E_COUNT_REPO   mongo | postgres: also check the counts in that database (optional)
E2E_RELEASE_MODE off (default) | shadow | canary: the app's RELEASE_MODE; tests marked
                 release_mode(<other mode>) are deselected
"""

import os
import time

import pytest
import requests

STARTUP_TIMEOUT = 300


def pytest_collection_modifyitems(config, items):
    """Keeps only the release tests for the mode the stack runs in (deselected, not skipped)."""
    mode = os.environ.get("E2E_RELEASE_MODE", "off")
    selected, deselected = [], []
    for item in items:
        marker = item.get_closest_marker("release_mode")
        (deselected if marker and marker.args[0] != mode else selected).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


@pytest.fixture(scope="session")
def base_url() -> str:
    url = os.environ.get("E2E_BASE_URL")
    if not url:
        pytest.skip("E2E_BASE_URL not set; start the stack and run `make test-e2e`")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def api(base_url) -> requests.Session:
    """A session against the app, once the app and every model in TF Serving are ready."""
    session = requests.Session()
    models = _wait_for(lambda: session.get(f"{base_url}/models", timeout=5).json(), "the app")
    tfs_url = os.environ.get("E2E_TFS_URL", "http://localhost:8501").rstrip("/")
    for model in models["models"]:
        versions = [model["version"]]
        if "release" in model:
            versions.append(model["release"]["candidate_version"])
        for version in versions:
            status_url = f"{tfs_url}/v1/models/{model['name']}/versions/{version}"
            _wait_for(
                lambda url=status_url: _model_state(url) == "AVAILABLE" or None,
                f"TF Serving to load {model['name']} v{version}",
            )
    return session


def _model_state(status_url: str) -> str | None:
    statuses = requests.get(status_url, timeout=5).json().get("model_version_status", [])
    return statuses[0]["state"] if statuses else None


def _wait_for(probe, what: str):
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while True:
        try:
            if (result := probe()) is not None:
                return result
        except (requests.RequestException, ValueError, KeyError):
            pass
        if time.monotonic() > deadline:
            pytest.fail(f"Timed out after {STARTUP_TIMEOUT} s waiting for {what}")
        time.sleep(2)
