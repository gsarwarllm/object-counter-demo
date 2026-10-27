"""Black-box tests against the running stack: app container, TF Serving with the real models
pulled from the registry, and a real database. Only HTTP (and, optionally, a database query)
is used, as a client would.

Model outputs aren't asserted exactly (scores vary between model versions); the tests check
properties: the expected class is found, scores are sorted and in range, boxes are valid.
"""

import io
import json
import os
import time
from pathlib import Path

import psycopg
import pytest
import yaml
from openapi_core import Config, OpenAPI
from openapi_core.contrib.requests import RequestsOpenAPIRequest, RequestsOpenAPIResponse
from PIL import Image
from prometheus_client.parser import text_string_to_metric_families
from pymongo import MongoClient

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).parents[2]
IMAGES = REPO_ROOT / "resources" / "images"
LOCK = REPO_ROOT / "tmp" / "model" / "models.lock.json"
SPEC = yaml.safe_load((REPO_ROOT / "docs" / "openapi.yaml").read_text())
VALIDATOR = OpenAPI.from_dict(
    SPEC, config=Config(extra_media_type_deserializers={"application/problem+json": json.loads})
)
DEFAULT_MODEL = "ssd_mobilenet_v2"
INTERNAL_MODEL = "acme_shelf_detector"


def image(name: str = "cat.jpg", mode: str | None = None) -> bytes:
    if mode is None:
        return (IMAGES / name).read_bytes()
    buffer = io.BytesIO()
    Image.open(IMAGES / name).convert(mode).save(buffer, "PNG")
    return buffer.getvalue()


def post(api, base_url, path, image_bytes=None, **fields):
    response = api.post(
        f"{base_url}{path}",
        files={"file": ("image", image_bytes or image())},
        data=fields,
        timeout=60,
    )
    VALIDATOR.validate_response(
        RequestsOpenAPIRequest(response.request), RequestsOpenAPIResponse(response)
    )
    return response


def get(api, base_url, path, **params):
    response = api.get(f"{base_url}{path}", params=params, timeout=10)
    VALIDATOR.validate_response(
        RequestsOpenAPIRequest(response.request), RequestsOpenAPIResponse(response)
    )
    return response


def predicted_classes(body) -> list[str]:
    return [prediction["class_name"] for prediction in body["predictions"]]


def totals(api, base_url) -> dict[str, int]:
    # threshold 1.0 counts nothing (real scores are below 1), so this only reads the totals
    body = post(api, base_url, "/object-count", threshold="1.0").json()
    assert body["current_objects"] == []
    return {count["object_class"]: count["count"] for count in body["total_objects"]}


def database_totals() -> dict[str, int] | None:
    store = os.environ.get("E2E_COUNT_REPO")
    if store == "postgres":
        with psycopg.connect("host=localhost dbname=counter user=counter password=counter") as c:
            return dict(c.execute("SELECT object_class, count FROM object_counts").fetchall())
    if store == "mongo":
        documents = MongoClient("localhost", 27017)["prod_counter"].counter.find()
        return {document["object_class"]: document["count"] for document in documents}
    return None


def test_models_are_served_at_the_pulled_versions(api, base_url):
    response = api.get(f"{base_url}/models", timeout=10)
    VALIDATOR.validate_response(
        RequestsOpenAPIRequest(response.request), RequestsOpenAPIResponse(response)
    )
    body = response.json()

    assert body["default_model"] == DEFAULT_MODEL
    assert {model["name"]: model["version"] for model in body["models"]} == json.loads(
        LOCK.read_text()
    )


def test_default_model_detects_the_cat(api, base_url):
    body = post(api, base_url, "/object-predictions", threshold="0.5").json()

    assert "cat" in predicted_classes(body)
    assert body["model"]["name"] == DEFAULT_MODEL
    scores = [prediction["score"] for prediction in body["predictions"]]
    assert scores == sorted(scores, reverse=True)
    assert all(0.5 <= score <= 1 for score in scores)
    for prediction in body["predictions"]:
        box = prediction["box"]
        assert 0 <= box["xmin"] <= box["xmax"] <= 1
        assert 0 <= box["ymin"] <= box["ymax"] <= 1


def test_default_model_detects_the_person(api, base_url):
    body = post(api, base_url, "/object-predictions", image("boy.jpg"), threshold="0.5").json()

    assert "person" in predicted_classes(body)


def test_internal_model_is_a_different_model(api, base_url):
    default = post(api, base_url, "/object-predictions", threshold="0.3").json()
    internal = post(
        api, base_url, "/object-predictions", threshold="0.3", model_name=INTERNAL_MODEL
    ).json()

    assert internal["model"]["name"] == INTERNAL_MODEL
    assert "cat" in predicted_classes(internal)
    # Different weights give different scores for the same image.
    assert internal["predictions"] != default["predictions"]


@pytest.mark.parametrize("mode", ["RGBA", "L"])
def test_png_with_alpha_or_greyscale_is_detected(api, base_url, mode):
    response = post(api, base_url, "/object-predictions", image(mode=mode), threshold="0.3")

    assert response.status_code == 200
    assert "cat" in predicted_classes(response.json())


def test_counting_adds_to_the_persisted_totals(api, base_url):
    before = totals(api, base_url)

    body = post(api, base_url, "/object-count", threshold="0.5").json()

    current = {count["object_class"]: count["count"] for count in body["current_objects"]}
    assert current.get("cat", 0) >= 1
    after = {count["object_class"]: count["count"] for count in body["total_objects"]}
    for object_class, number in current.items():
        assert after[object_class] == before.get(object_class, 0) + number
    if (stored := database_totals()) is not None:
        assert stored == after


def test_predictions_do_not_change_the_totals(api, base_url):
    before = totals(api, base_url)

    post(api, base_url, "/object-predictions", threshold="0.1")

    assert totals(api, base_url) == before


@pytest.mark.parametrize(
    ("fields", "image_bytes", "field"),
    [
        ({"threshold": "2"}, None, "threshold"),
        ({"model_name": "unknown"}, None, "model_name"),
    ],
)
def test_invalid_requests_get_problem_json(api, base_url, fields, image_bytes, field):
    response = post(api, base_url, "/object-count", image_bytes, **fields)

    assert response.status_code == 400
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["errors"][0]["field"] == field


def test_api_docs_are_served(api, base_url):
    assert yaml.safe_load(api.get(f"{base_url}/openapi.yaml", timeout=10).text) == SPEC
    assert "swagger-ui" in api.get(f"{base_url}/docs/", timeout=10).text


def test_alive_and_ready_with_every_pulled_model(api, base_url):
    assert get(api, base_url, "/health").json() == {"status": "ok"}

    response = get(api, base_url, "/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {
        "repository": "ok",
        "detectors": dict.fromkeys(json.loads(LOCK.read_text()), "ok"),
    }


def test_object_counts_reads_the_same_totals(api, base_url):
    post(api, base_url, "/object-count", threshold="0.5")
    expected = totals(api, base_url)

    everything = get(api, base_url, "/object-counts").json()["total_objects"]
    only_cats = get(api, base_url, "/object-counts", object_class="cat").json()["total_objects"]

    assert {count["object_class"]: count["count"] for count in everything} == expected
    assert only_cats == [{"object_class": "cat", "count": expected["cat"]}]
    if (stored := database_totals()) is not None:
        assert stored == expected


def test_metrics_and_request_ids(api, base_url):
    response = post(api, base_url, "/object-predictions", threshold="0.5")
    traced = api.get(f"{base_url}/health", headers={"X-Request-ID": "e2e-trace-1"}, timeout=10)
    metrics = api.get(f"{base_url}/metrics", timeout=10).text

    assert len(response.headers["X-Request-ID"]) == 32  # generated when the client sends none
    assert traced.headers["X-Request-ID"] == "e2e-trace-1"
    # Served by gunicorn with several workers: the counters are added up across them.
    samples = {
        (sample.name, tuple(sorted(sample.labels.items()))): sample.value
        for family in text_string_to_metric_families(metrics)
        for sample in family.samples
    }
    version = json.loads(LOCK.read_text())[DEFAULT_MODEL]
    detector_ok = (("model", DEFAULT_MODEL), ("outcome", "ok"), ("version", version))
    assert samples[("detector_requests_total", detector_ok)] >= 1
    http_ok = (("method", "POST"), ("route", "/object-predictions"), ("status", "200"))
    assert samples[("http_requests_total", http_ok)] >= 1


def test_predictions_are_logged_and_compared_with_the_baseline(api, base_url):
    """CI computes the baselines (`baseline`) right after the stack starts, with
    DRIFT_MIN_IMAGES=1 so the drift of a few requests is reported."""
    version = json.loads(LOCK.read_text())[DEFAULT_MODEL]
    post(api, base_url, "/object-predictions", threshold="0.5")

    logged = _wait_for_logged_predictions(DEFAULT_MODEL, version)
    samples = {
        (sample.name, tuple(sorted(sample.labels.items()))): sample.value
        for family in text_string_to_metric_families(
            api.get(f"{base_url}/metrics", timeout=10).text
        )
        for sample in family.samples
    }

    assert logged[1] > 1  # every raw score is kept, not only those above the threshold
    # Prediction features, and input features from the image statistics (X4)
    for feature in ("scores", "detections", "classes", "brightness", "color_mode"):
        labels = (("feature", feature), ("model", DEFAULT_MODEL), ("version", version))
        assert samples[("model_drift_psi", labels)] >= 0


def _wait_for_logged_predictions(model: str, version: str, timeout: float = 15.0):
    """(rows, most scores in one row) once a row exists; records are written in the background."""
    deadline = time.monotonic() + timeout
    while True:
        with psycopg.connect("host=localhost dbname=counter user=counter password=counter") as c:
            logged = c.execute(
                "SELECT count(*), max(cardinality(scores)) FROM prediction_logs "
                "WHERE model = %s AND version = %s",
                (model, version),
            ).fetchone()
        if logged[0] >= 1 or time.monotonic() > deadline:
            assert logged[0] >= 1, f"no prediction of {model}@{version} logged"
            return logged
        time.sleep(0.5)
