"""The monitoring profile against the running stack: Prometheus scrapes the app and TF Serving,
the app's metrics arrive, every dashboard query is valid, and Grafana loaded the dashboard.

E2E_PROMETHEUS_URL  e.g. http://localhost:9090 (tests are skipped when unset)
E2E_GRAFANA_URL     e.g. http://localhost:3000
"""

import json
import os
import time
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.e2e

DASHBOARD = (
    Path(__file__).parents[2] / "monitoring" / "grafana" / "dashboards" / "object-counter.json"
)
# Prometheus scrapes every 15 s, so a new value can take that long to show up.
SCRAPE_WAIT = 60


@pytest.fixture(scope="module")
def prometheus() -> str:
    url = os.environ.get("E2E_PROMETHEUS_URL")
    if not url:
        pytest.skip("E2E_PROMETHEUS_URL not set; start the monitoring profile (`make e2e-up`)")
    return url.rstrip("/")


@pytest.fixture(scope="module")
def grafana() -> str:
    url = os.environ.get("E2E_GRAFANA_URL")
    if not url:
        pytest.skip("E2E_GRAFANA_URL not set; start the monitoring profile (`make e2e-up`)")
    return url.rstrip("/")


def query(prometheus: str, expr: str) -> list[dict]:
    response = requests.get(f"{prometheus}/api/v1/query", params={"query": expr}, timeout=10)
    body = response.json()
    assert body["status"] == "success", body
    return body["data"]["result"]


def eventually(probe, what: str):
    deadline = time.monotonic() + SCRAPE_WAIT
    while not (result := probe()):
        if time.monotonic() > deadline:
            pytest.fail(f"Timed out after {SCRAPE_WAIT} s waiting for {what}")
        time.sleep(3)
    return result


def test_prometheus_scrapes_the_app_and_tf_serving(prometheus):
    def healthy_jobs():
        targets = requests.get(f"{prometheus}/api/v1/targets", timeout=10).json()
        jobs = {t["labels"]["job"] for t in targets["data"]["activeTargets"] if t["health"] == "up"}
        return jobs >= {"object-counter", "tfserving"}

    eventually(healthy_jobs, "both scrape targets to be up")


def test_detector_metrics_reach_prometheus(api, base_url, prometheus):
    api.post(f"{base_url}/object-predictions", files={"file": ("image", _cat())}, timeout=60)

    result = eventually(
        lambda: query(prometheus, 'sum by (model) (detector_requests_total{outcome="ok"})'),
        "detector metrics",
    )

    assert {series["metric"]["model"] for series in result} >= {"ssd_mobilenet_v2"}


def test_every_dashboard_query_is_valid_promql(prometheus):
    panels = json.loads(DASHBOARD.read_text())["panels"]

    for panel in panels:
        for target in panel["targets"]:
            query(prometheus, target["expr"])  # fails on a syntax error


def test_grafana_loaded_the_datasource_and_the_dashboard(grafana):
    admin = ("admin", os.environ.get("GRAFANA_ADMIN_PASSWORD", "admin"))

    health = requests.get(
        f"{grafana}/api/datasources/uid/prometheus/health", auth=admin, timeout=10
    )
    dashboard = requests.get(f"{grafana}/api/dashboards/uid/object-counter", auth=admin, timeout=10)

    assert health.json()["status"] == "OK", health.text
    assert dashboard.status_code == 200
    assert len(dashboard.json()["dashboard"]["panels"]) == len(
        json.loads(DASHBOARD.read_text())["panels"]
    )


def _cat() -> bytes:
    return (Path(__file__).parents[2] / "resources" / "images" / "cat.jpg").read_bytes()


def test_prometheus_loaded_the_alert_rules(prometheus):
    groups = requests.get(f"{prometheus}/api/v1/rules", timeout=10).json()["data"]["groups"]

    rules = {rule["name"] for group in groups for rule in group["rules"]}
    assert rules >= {
        "ModelDrift",
        "InputDrift",
        "HighServerErrorRate",
        "DetectorUnavailable",
        "CandidateUnhealthy",
    }
