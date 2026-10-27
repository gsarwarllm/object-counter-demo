"""The app in prod mode talking HTTP to a stub TF Serving (no Docker needed).

Exercises the real composition root, detector factory, label maps, version pinning, HTTP
client and error mapping; only TF Serving itself is replaced.
"""

import io
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from counter.adapters.model_manifest import write_lock
from counter.entrypoints.webapp import create_app
from tests.integration.stub_tf_serving import StubTFServing

IMAGE = Path(__file__).parents[2] / "resources" / "images" / "cat.jpg"
PULLED_VERSIONS = {"ssd_mobilenet_v2": "3", "acme_shelf_detector": "5"}
THUMBNAIL_SIZE = (64, 64)


@pytest.fixture
def tf_serving():
    stub = StubTFServing().start()
    yield stub
    stub.stop()


@pytest.fixture
def client(tf_serving, monkeypatch, tmp_path):
    lock = tmp_path / "models.lock.json"
    write_lock(PULLED_VERSIONS, lock)
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("TFS_HOST", "127.0.0.1")
    monkeypatch.setenv("TFS_PORT", str(tf_serving.port))
    monkeypatch.setenv("TFS_TIMEOUT", "0.5")
    monkeypatch.setenv("MODELS_LOCK", str(lock))
    monkeypatch.setenv("COUNT_REPO", "memory")
    monkeypatch.setenv("PREDICTION_LOG", "memory")
    with create_app().test_client() as client:
        yield client


def thumbnail(mode: str = "RGB", image_format: str = "JPEG") -> bytes:
    """cat.jpg scaled down: a real photo, but a small JSON payload for TF Serving."""
    buffer = io.BytesIO()
    image = Image.open(IMAGE).convert(mode)
    image.thumbnail(THUMBNAIL_SIZE)
    image.save(buffer, image_format)
    return buffer.getvalue()


def upload(image_bytes=None, **fields):
    return {"file": (io.BytesIO(image_bytes or thumbnail()), "image"), **fields}


def post(client, path, data):
    return client.post(path, data=data, content_type="multipart/form-data")


def test_predictions_are_mapped_from_the_tf_serving_response(client, tf_serving):
    body = post(client, "/object-predictions", upload(threshold="0.5")).get_json()

    # Recorded response: 3 real detections (cat 0.97, dog 0.64, person 0.12) plus padding.
    assert [(p["class_name"], p["score"]) for p in body["predictions"]] == [
        ("cat", 0.97),
        ("dog", 0.64),
    ]
    assert body["predictions"][0]["box"] == {
        "xmin": 0.367,
        "ymin": 0.278,
        "xmax": 0.736,
        "ymax": 0.699,
    }
    assert body["model"] == {"name": "ssd_mobilenet_v2", "version": "3"}


def test_requests_are_pinned_to_the_pulled_version(client, tf_serving):
    post(client, "/object-predictions", upload())
    post(client, "/object-predictions", upload(model_name="acme_shelf_detector"))

    assert [request["path"] for request in tf_serving.requests] == [
        "/v1/models/ssd_mobilenet_v2/versions/3:predict",
        "/v1/models/acme_shelf_detector/versions/5:predict",
    ]


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "P"])
def test_tf_serving_receives_a_uint8_rgb_batch_for_any_image_mode(client, tf_serving, mode):
    image_bytes = thumbnail(mode, "PNG")
    response = post(client, "/object-predictions", upload(image_bytes))

    assert response.status_code == 200
    instances = np.array(tf_serving.requests[0]["body"]["instances"])
    width, height = Image.open(io.BytesIO(image_bytes)).size
    assert instances.shape == (1, height, width, 3)
    assert instances.min() >= 0
    assert instances.max() <= 255


def test_counts_accumulate_through_tf_serving(client, tf_serving):
    post(client, "/object-count", upload(threshold="0.5"))
    body = post(client, "/object-count", upload(threshold="0.5")).get_json()

    assert sorted(body["current_objects"], key=lambda c: c["object_class"]) == [
        {"object_class": "cat", "count": 1},
        {"object_class": "dog", "count": 1},
    ]
    assert sorted(body["total_objects"], key=lambda c: c["object_class"]) == [
        {"object_class": "cat", "count": 2},
        {"object_class": "dog", "count": 2},
    ]


@pytest.mark.parametrize("mode", ["error", "malformed", "slow"])
def test_tf_serving_failures_become_503(client, tf_serving, mode):
    tf_serving.mode = mode
    started = time.monotonic()

    response = post(client, "/object-count", upload())

    assert response.status_code == 503
    assert response.get_json()["title"] == "Object detector unavailable"
    assert time.monotonic() - started < 2.0  # the 0.5 s timeout cuts the slow case short


def test_tf_serving_down_becomes_503(client, tf_serving):
    tf_serving.stop()

    response = post(client, "/object-predictions", upload())

    assert response.status_code == 503
    assert response.mimetype == "application/problem+json"


def test_ready_checks_each_pinned_model_version(client, tf_serving):
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.get_json()["checks"]["detectors"] == {
        "acme_shelf_detector": "ok",
        "ssd_mobilenet_v2": "ok",
    }
    assert sorted(request["path"] for request in tf_serving.requests) == [
        "/v1/models/acme_shelf_detector/versions/5",
        "/v1/models/ssd_mobilenet_v2/versions/3",
    ]


@pytest.mark.parametrize(("mode", "state"), [("ok", "LOADING"), ("error", "AVAILABLE")])
def test_not_ready_while_models_load_or_tf_serving_fails(client, tf_serving, mode, state):
    tf_serving.mode, tf_serving.model_state = mode, state

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.get_json()["status"] == "unavailable"


def test_not_ready_when_tf_serving_is_down_but_still_alive(client, tf_serving):
    tf_serving.stop()

    assert client.get("/health/ready").status_code == 503
    assert client.get("/health").status_code == 200
