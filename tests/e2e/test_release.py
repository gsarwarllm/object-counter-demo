"""Shadow and canary releases (X6) against the running stack with real models.

CI publishes a second version of acme_shelf_detector, points the candidate alias at it, pulls,
and restarts the app with RELEASE_MODE=shadow, then canary with CANARY_PERCENT=100. Each test
runs only in its mode (E2E_RELEASE_MODE, see conftest.py).
"""

import os
import time
from pathlib import Path

import pytest
import requests
from prometheus_client.parser import text_string_to_metric_families

from counter.entrypoints import release_check

pytestmark = pytest.mark.e2e

MODEL = "acme_shelf_detector"
CAT = Path(__file__).parents[2] / "resources" / "images" / "cat.jpg"
WAIT = 60


def release(api, base_url):
    models = api.get(f"{base_url}/models", timeout=10).json()["models"]
    return next(model for model in models if model["name"] == MODEL)


def post(api, base_url, path):
    with open(CAT, "rb") as image:
        response = api.post(
            f"{base_url}{path}",
            data={"model_name": MODEL, "threshold": "0.5"},
            files={"file": ("cat.jpg", image, "image/jpeg")},
            timeout=60,
        )
    assert response.status_code == 200, response.text
    return response.json()


def sample(api, base_url, name, **labels):
    text = api.get(f"{base_url}/metrics", timeout=10).text
    for family in text_string_to_metric_families(text):
        for metric in family.samples:
            if metric.name == name and labels.items() <= metric.labels.items():
                return metric.value
    return 0.0


def eventually(probe, what):
    deadline = time.monotonic() + WAIT
    while not (result := probe()):
        if time.monotonic() > deadline:
            pytest.fail(f"Timed out after {WAIT} s waiting for {what}")
        time.sleep(2)
    return result


@pytest.mark.release_mode("shadow")
def test_shadow_answers_with_the_champion(api, base_url):
    model = release(api, base_url)
    assert model["release"]["mode"] == "shadow"

    body = post(api, base_url, "/object-predictions")

    assert body["model"] == {"name": MODEL, "version": model["version"]}
    assert "cat" in {prediction["class_name"] for prediction in body["predictions"]}


@pytest.mark.release_mode("shadow")
def test_shadow_calls_reach_the_candidate_and_are_compared(api, base_url):
    candidate = release(api, base_url)["release"]["candidate_version"]
    labels = {"model": MODEL, "version": candidate}
    before = sample(api, base_url, "shadow_requests_total", outcome="compared", **labels)

    post(api, base_url, "/object-count")

    eventually(
        lambda: (
            sample(api, base_url, "shadow_requests_total", outcome="compared", **labels) > before
        ),
        "the shadow call to be compared",
    )
    assert sample(api, base_url, "detector_requests_total", outcome="ok", **labels) >= 1
    assert sample(api, base_url, "shadow_class_agreement_count", **labels) >= 1


@pytest.mark.release_mode("canary")
def test_canary_answers_with_the_candidate(api, base_url):
    model = release(api, base_url)
    assert model["release"] == {
        "mode": "canary",
        "candidate_version": model["release"]["candidate_version"],
        "canary_percent": 100,
    }

    body = post(api, base_url, "/object-count")

    assert body["model"] == {"name": MODEL, "version": model["release"]["candidate_version"]}
    assert "cat" in {count["object_class"] for count in body["current_objects"]}


@pytest.mark.release_mode("canary")
def test_release_check_reads_the_canary_from_prometheus(api, base_url, capsys):
    prometheus = os.environ.get("E2E_PROMETHEUS_URL")
    if not prometheus:
        pytest.skip("E2E_PROMETHEUS_URL not set")
    candidate = release(api, base_url)["release"]["candidate_version"]

    def scraped():
        query = f'model_release_info{{model="{MODEL}",role="candidate",version="{candidate}"}}'
        result = requests.get(
            f"{prometheus}/api/v1/query", params={"query": query}, timeout=10
        ).json()
        return result["data"]["result"]

    eventually(scraped, "Prometheus to scrape the canary's release info")

    code = release_check.main(
        [MODEL, "--prometheus", prometheus, "--window", "10m", "--min-requests", "1"]
    )

    # Real PromQL against real data: the verdict depends on timing, the check must run.
    assert code in (0, 1), capsys.readouterr().err
