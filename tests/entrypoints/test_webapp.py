import io
import json
from pathlib import Path

import pytest

from counter.entrypoints.webapp import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def image_path():
    ref_dir = Path(__file__).parent
    return ref_dir.parent.parent / "resources" / "images" / "boy.jpg"


def test_object_detection(client, image_path):
    # Load the image from the path resource/boy.jpg
    with open(image_path, "rb") as f:
        image_data = f.read()
    image = io.BytesIO(image_data)

    data = {
        "threshold": "0.9",
        "model_name": "ssd_mobilenet_v2",
    }
    data["file"] = (image, "test.jpg")

    # Make a test request to the object_detection endpoint
    response = client.post(
        "/object-count", data=data, content_type="multipart/form-data", buffered=True
    )

    # Check that the count_action was called with the correct arguments and
    # and status code is correct(Integration test)
    assert response.status_code == 200
    assert json.loads(response.data) is not None


def post_predictions(client, data):
    return client.post(
        "/object-predictions", data=data, content_type="multipart/form-data", buffered=True
    )


def image_file(image_path):
    with open(image_path, "rb") as f:
        return io.BytesIO(f.read()), "test.jpg"


def test_object_predictions(client, image_path):
    response = post_predictions(client, {"threshold": "0.5", "file": image_file(image_path)})

    assert response.status_code == 200
    body = response.get_json()
    assert body["threshold"] == 0.5
    assert body["count"] == len(body["predictions"]) == 1
    assert body["predictions"][0]["class_name"] == "cat"
    assert set(body["predictions"][0]["box"]) == {"xmin", "ymin", "xmax", "ymax"}


def test_object_predictions_filters_by_threshold(client, image_path):
    response = post_predictions(client, {"threshold": "1.0", "file": image_file(image_path)})

    assert response.status_code == 200
    assert response.get_json() == {"threshold": 1.0, "count": 0, "predictions": []}


def test_object_predictions_does_not_change_totals(client, image_path):
    count_data = {"threshold": "0.5", "file": image_file(image_path)}
    totals_before = client.post(
        "/object-count", data=count_data, content_type="multipart/form-data", buffered=True
    ).get_json()["total_objects"]

    post_predictions(client, {"threshold": "0.5", "file": image_file(image_path)})

    count_data = {"threshold": "1.0", "file": image_file(image_path)}
    totals_after = client.post(
        "/object-count", data=count_data, content_type="multipart/form-data", buffered=True
    ).get_json()["total_objects"]
    assert totals_after == totals_before


@pytest.mark.parametrize("threshold", ["abc", "1.5", "-0.1"])
def test_object_predictions_rejects_invalid_threshold(client, image_path, threshold):
    response = post_predictions(client, {"threshold": threshold, "file": image_file(image_path)})

    assert response.status_code == 400
    assert response.mimetype == "application/problem+json"
    assert response.get_json()["errors"][0]["field"] == "threshold"


def test_object_predictions_requires_file(client):
    response = post_predictions(client, {"threshold": "0.5"})

    assert response.status_code == 400
    assert response.mimetype == "application/problem+json"
    assert response.get_json()["errors"][0]["field"] == "file"


def test_object_predictions_rejects_non_image(client):
    response = post_predictions(
        client, {"threshold": "0.5", "file": (io.BytesIO(b"not an image"), "test.txt")}
    )

    assert response.status_code == 400
    assert response.mimetype == "application/problem+json"
    assert response.get_json()["title"] == "Invalid image"


def test_object_count_returns_503_when_count_store_is_down(monkeypatch, image_path):
    monkeypatch.setenv("COUNT_REPO", "postgres")
    monkeypatch.setenv("DATABASE_URL", "host=127.0.0.1 port=1 dbname=counter user=counter")
    monkeypatch.setenv("POSTGRES_TIMEOUT", "0.5")
    app = create_app()

    with app.test_client() as client:
        response = client.post(
            "/object-count",
            data={"threshold": "0.5", "file": image_file(image_path)},
            content_type="multipart/form-data",
        )

    assert response.status_code == 503
    assert response.mimetype == "application/problem+json"
    assert response.get_json()["title"] == "Service unavailable"
