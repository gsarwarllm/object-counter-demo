import io
from pathlib import Path
from unittest.mock import Mock

import pytest

from counter.adapters.count_repo import CountInMemoryRepo
from counter.domain.actions import CountDetectedObjects, DetectObjects
from counter.domain.errors import DetectorUnavailableError
from counter.entrypoints.webapp import create_app

ENDPOINTS = ["/object-count", "/object-predictions"]
UNREACHABLE_POSTGRES = "host=127.0.0.1 port=1 dbname=counter user=counter"


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def image_path():
    return Path(__file__).parent.parent.parent / "resources" / "images" / "boy.jpg"


def image_file(image_path):
    with open(image_path, "rb") as f:
        return io.BytesIO(f.read()), "test.jpg"


def post(client, path, data):
    return client.post(path, data=data, content_type="multipart/form-data", buffered=True)


def assert_problem(response, status, title):
    assert response.status_code == status
    assert response.mimetype == "application/problem+json"
    body = response.get_json()
    assert body["status"] == status
    assert body["title"] == title
    return body


def test_object_count(client, image_path):
    response = post(client, "/object-count", {"threshold": "0.9", "file": image_file(image_path)})

    assert response.status_code == 200
    assert response.get_json() == {
        "current_objects": [{"object_class": "cat", "count": 1}],
        "total_objects": [{"object_class": "cat", "count": 1}],
    }


def test_object_count_accumulates_totals(client, image_path):
    post(client, "/object-count", {"threshold": "0.9", "file": image_file(image_path)})
    response = post(client, "/object-count", {"threshold": "0.9", "file": image_file(image_path)})

    assert response.get_json()["total_objects"] == [{"object_class": "cat", "count": 2}]


def test_object_count_uses_default_threshold(client, image_path):
    response = post(client, "/object-count", {"file": image_file(image_path)})

    assert response.status_code == 200


def test_object_predictions(client, image_path):
    response = post(
        client, "/object-predictions", {"threshold": "0.5", "file": image_file(image_path)}
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["threshold"] == 0.5
    assert body["count"] == len(body["predictions"]) == 1
    assert body["predictions"][0]["class_name"] == "cat"
    assert set(body["predictions"][0]["box"]) == {"xmin", "ymin", "xmax", "ymax"}


def test_object_predictions_filters_by_threshold(client, image_path):
    response = post(
        client, "/object-predictions", {"threshold": "1.0", "file": image_file(image_path)}
    )

    assert response.status_code == 200
    assert response.get_json() == {"threshold": 1.0, "count": 0, "predictions": []}


def test_object_predictions_does_not_change_totals(client, image_path):
    count_data = {"threshold": "0.5", "file": image_file(image_path)}
    totals_before = post(client, "/object-count", count_data).get_json()["total_objects"]

    post(client, "/object-predictions", {"threshold": "0.5", "file": image_file(image_path)})

    count_data = {"threshold": "1.0", "file": image_file(image_path)}
    totals_after = post(client, "/object-count", count_data).get_json()["total_objects"]
    assert totals_after == totals_before


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.parametrize("threshold", ["abc", "1.5", "-0.1"])
def test_rejects_invalid_threshold(client, image_path, path, threshold):
    response = post(client, path, {"threshold": threshold, "file": image_file(image_path)})

    body = assert_problem(response, 400, "Invalid request")
    assert body["errors"][0]["field"] == "threshold"


@pytest.mark.parametrize("path", ENDPOINTS)
def test_requires_file(client, path):
    response = post(client, path, {"threshold": "0.5"})

    body = assert_problem(response, 400, "Invalid request")
    assert body["errors"][0]["field"] == "file"


@pytest.mark.parametrize("path", ENDPOINTS)
def test_rejects_non_image(client, path):
    response = post(
        client, path, {"threshold": "0.5", "file": (io.BytesIO(b"not an image"), "test.txt")}
    )

    assert_problem(response, 400, "Invalid image")


@pytest.mark.parametrize("path", ENDPOINTS)
def test_rejects_upload_over_the_limit(monkeypatch, image_path, path):
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")
    app = create_app()

    with app.test_client() as client:
        response = post(client, path, {"threshold": "0.5", "file": image_file(image_path)})

    assert_problem(response, 413, "Payload too large")


@pytest.mark.parametrize("path", ENDPOINTS)
def test_returns_503_when_detector_is_down(image_path, path):
    detector = Mock()
    detector.predict.side_effect = DetectorUnavailableError("connection refused")
    app = create_app(
        count_action=CountDetectedObjects(detector, CountInMemoryRepo()),
        detect_action=DetectObjects(detector),
    )

    with app.test_client() as client:
        response = post(client, path, {"threshold": "0.5", "file": image_file(image_path)})

    assert_problem(response, 503, "Object detector unavailable")


def test_object_count_returns_503_when_count_store_is_down(monkeypatch, image_path):
    monkeypatch.setenv("COUNT_REPO", "postgres")
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_POSTGRES)
    monkeypatch.setenv("POSTGRES_TIMEOUT", "0.5")
    app = create_app()

    with app.test_client() as client:
        response = post(
            client, "/object-count", {"threshold": "0.5", "file": image_file(image_path)}
        )

    assert_problem(response, 503, "Count repository unavailable")


def test_unexpected_error_returns_500_without_details(image_path):
    detector = Mock()
    detector.predict.side_effect = RuntimeError("secret internal detail")
    app = create_app(
        count_action=CountDetectedObjects(detector, CountInMemoryRepo()),
        detect_action=DetectObjects(detector),
    )

    with app.test_client() as client:
        response = post(
            client, "/object-count", {"threshold": "0.5", "file": image_file(image_path)}
        )

    body = assert_problem(response, 500, "Internal server error")
    assert "secret" not in response.get_data(as_text=True)
    assert body["instance"] == "/object-count"


def test_unknown_route_returns_problem_json(client):
    assert_problem(client.get("/nope"), 404, "Not Found")


def test_wrong_method_returns_problem_json(client):
    assert_problem(client.get("/object-count"), 405, "Method Not Allowed")
