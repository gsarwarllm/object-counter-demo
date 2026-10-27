import io
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
from prometheus_client import REGISTRY

from counter.adapters.count_repo import CountInMemoryRepo
from counter.adapters.detector_registry import Candidate, DetectorRegistry, ServedModel
from counter.adapters.object_detector import FakeObjectDetector
from counter.config import ReleaseSettings
from counter.domain.errors import DetectorUnavailableError, RepositoryUnavailableError
from counter.domain.models import Box, Prediction
from counter.entrypoints.webapp import create_app

ENDPOINTS = ["/object-count", "/object-predictions"]
DEFAULT_MODEL = {"name": "ssd_mobilenet_v2", "version": None}  # dev: fakes, no pinned version
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


def app_with_detector(detector):
    """An app serving one model backed by the given detector."""
    detectors = DetectorRegistry([ServedModel("only_model", "1", detector)], "only_model")
    return create_app(detectors=detectors, count_repo=CountInMemoryRepo())


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
        "model": DEFAULT_MODEL,
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
    assert body["model"] == DEFAULT_MODEL


def test_object_predictions_filters_by_threshold(client, image_path):
    response = post(
        client, "/object-predictions", {"threshold": "1.0", "file": image_file(image_path)}
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "threshold": 1.0,
        "count": 0,
        "predictions": [],
        "model": DEFAULT_MODEL,
    }


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
    app = app_with_detector(detector)

    with app.test_client() as client:
        response = post(client, path, {"threshold": "0.5", "file": image_file(image_path)})

    assert_problem(response, 503, "Object detector unavailable")


def test_logs_the_cause_of_a_503(image_path, caplog):
    detector = Mock()
    detector.predict.side_effect = DetectorUnavailableError("connection refused")
    app = app_with_detector(detector)

    with app.test_client() as client, caplog.at_level(logging.ERROR):
        post(client, "/object-count", {"threshold": "0.5", "file": image_file(image_path)})

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == ["Object detector unavailable: connection refused"]


def test_unexpected_error_is_logged_with_traceback(image_path, caplog):
    detector = Mock()
    detector.predict.side_effect = RuntimeError("secret internal detail")
    app = app_with_detector(detector)

    with app.test_client() as client, caplog.at_level(logging.ERROR):
        post(client, "/object-count", {"threshold": "0.5", "file": image_file(image_path)})

    (record,) = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert record.getMessage() == "Unhandled error"
    assert record.exc_info[1].args == ("secret internal detail",)


def test_logs_what_it_serves_at_startup(caplog):
    detectors = DetectorRegistry(
        [
            ServedModel("cat_model", "3", FakeObjectDetector()),
            ServedModel("dog_model", None, FakeObjectDetector()),
        ],
        default_model="cat_model",
    )
    with caplog.at_level(logging.INFO, logger="counter.entrypoints.webapp"):
        create_app(detectors=detectors, count_repo=CountInMemoryRepo())

    assert caplog.messages == [
        "Serving models cat_model@3, dog_model@latest (default cat_model), env=dev, "
        "count repo=CountInMemoryRepo, prediction log=InMemoryPredictionLog, debug images=off"
    ]


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
    app = app_with_detector(detector)

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


class DogDetector(FakeObjectDetector):
    def predict(self, image):
        return [Prediction("dog", 0.8, Box(0, 0, 1, 1))]


@pytest.fixture
def two_model_client():
    detectors = DetectorRegistry(
        [
            ServedModel("cat_model", "3", FakeObjectDetector()),
            ServedModel("dog_model", "7", DogDetector()),
        ],
        default_model="cat_model",
    )
    with create_app(detectors=detectors, count_repo=CountInMemoryRepo()).test_client() as client:
        yield client


@pytest.mark.parametrize(
    ("form", "expected_model", "expected_class"),
    [
        ({}, {"name": "cat_model", "version": "3"}, "cat"),
        ({"model_name": ""}, {"name": "cat_model", "version": "3"}, "cat"),
        ({"model_name": "dog_model"}, {"name": "dog_model", "version": "7"}, "dog"),
    ],
)
def test_model_name_selects_the_model(
    two_model_client, image_path, form, expected_model, expected_class
):
    data = {"threshold": "0.5", "file": image_file(image_path), **form}
    body = post(two_model_client, "/object-predictions", data).get_json()

    assert body["model"] == expected_model
    assert body["predictions"][0]["class_name"] == expected_class


def test_models_share_the_count_store(two_model_client, image_path):
    post(two_model_client, "/object-count", {"file": image_file(image_path)})
    data = {"file": image_file(image_path), "model_name": "dog_model"}
    body = post(two_model_client, "/object-count", data).get_json()

    assert body["current_objects"] == [{"object_class": "dog", "count": 1}]
    assert sorted(body["total_objects"], key=lambda c: c["object_class"]) == [
        {"object_class": "cat", "count": 1},
        {"object_class": "dog", "count": 1},
    ]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_unknown_model_is_rejected(two_model_client, image_path, path):
    data = {"threshold": "0.5", "file": image_file(image_path), "model_name": "gpt"}
    body = assert_problem(post(two_model_client, path, data), 400, "Invalid request")

    assert body["errors"] == [
        {"field": "model_name", "message": "unknown model 'gpt'; available: cat_model, dog_model"}
    ]


def test_list_models(two_model_client):
    response = two_model_client.get("/models")

    assert response.status_code == 200
    assert response.get_json() == {
        "default_model": "cat_model",
        "models": [{"name": "cat_model", "version": "3"}, {"name": "dog_model", "version": "7"}],
    }


def test_list_models_in_dev_shows_the_manifest_models(client):
    body = client.get("/models").get_json()

    assert body["default_model"] == "ssd_mobilenet_v2"
    assert [model["name"] for model in body["models"]] == [
        "acme_shelf_detector",
        "ssd_mobilenet_v2",
    ]


def count_image(client, image_path):
    post(client, "/object-count", {"threshold": "0.5", "file": image_file(image_path)})


def test_object_counts_returns_the_totals(client, image_path):
    assert client.get("/object-counts").get_json() == {"total_objects": []}
    count_image(client, image_path)
    count_image(client, image_path)

    response = client.get("/object-counts")

    assert response.status_code == 200
    assert response.get_json() == {"total_objects": [{"object_class": "cat", "count": 2}]}


def test_object_counts_filters_by_class(two_model_client, image_path):
    for model_name in ("cat_model", "dog_model"):
        form = {"model_name": model_name, "file": image_file(image_path)}
        post(two_model_client, "/object-count", form)

    response = two_model_client.get("/object-counts?object_class=dog&object_class=unicorn")

    assert response.get_json() == {"total_objects": [{"object_class": "dog", "count": 1}]}


def test_object_counts_rejects_an_empty_class(client):
    body = assert_problem(client.get("/object-counts?object_class="), 400, "Invalid request")
    assert body["errors"] == [{"field": "object_class", "message": "must not be empty"}]


def test_object_counts_returns_503_when_count_store_is_down(monkeypatch):
    monkeypatch.setenv("COUNT_REPO", "postgres")
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_POSTGRES)
    monkeypatch.setenv("POSTGRES_TIMEOUT", "0.5")

    with create_app().test_client() as client:
        assert_problem(client.get("/object-counts"), 503, "Count repository unavailable")


def test_liveness(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_ready_in_dev(client):
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "checks": {
            "repository": "ok",
            "detectors": {"acme_shelf_detector": "ok", "ssd_mobilenet_v2": "ok"},
        },
    }


class NotReadyDetector(FakeObjectDetector):
    def check_ready(self):
        raise DetectorUnavailableError("dog_model@7 is not available: ['LOADING']")


class DownRepo(CountInMemoryRepo):
    def check_ready(self):
        raise RepositoryUnavailableError("MongoDB unavailable: connection refused")


def readiness_of(detectors, count_repo):
    with create_app(detectors=detectors, count_repo=count_repo).test_client() as client:
        return client.get("/health/ready")


def test_not_ready_names_the_failing_model_and_logs_the_cause(caplog):
    detectors = DetectorRegistry(
        [
            ServedModel("cat_model", "3", FakeObjectDetector()),
            ServedModel("dog_model", "7", NotReadyDetector()),
        ],
        default_model="cat_model",
    )

    with caplog.at_level(logging.WARNING):
        response = readiness_of(detectors, CountInMemoryRepo())

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "unavailable",
        "checks": {
            "repository": "ok",
            "detectors": {"cat_model": "ok", "dog_model": "unavailable"},
        },
    }
    assert "LOADING" not in response.get_data(as_text=True)
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == ["Not ready: model dog_model: dog_model@7 is not available: ['LOADING']"]


def test_not_ready_when_the_count_store_is_down():
    detectors = DetectorRegistry([ServedModel("cat_model", "3", FakeObjectDetector())], "cat_model")

    response = readiness_of(detectors, DownRepo())

    assert response.status_code == 503
    assert response.get_json()["checks"]["repository"] == "unavailable"


def test_readiness_survives_an_unexpected_error():
    detector = Mock()
    detector.check_ready.side_effect = RuntimeError("bug")

    response = readiness_of(
        DetectorRegistry([ServedModel("m", "1", detector)], "m"), CountInMemoryRepo()
    )

    assert response.status_code == 503
    assert response.get_json()["checks"]["detectors"] == {"m": "unavailable"}


def test_generates_a_request_id(client):
    response = client.get("/health")

    assert len(response.headers["X-Request-ID"]) == 32


@pytest.mark.parametrize(
    ("incoming", "kept"), [("abc-123.x_Y", True), ("has spaces", False), ("x" * 129, False)]
)
def test_keeps_only_a_well_formed_request_id(client, incoming, kept):
    returned = client.get("/health", headers={"X-Request-ID": incoming}).headers["X-Request-ID"]

    assert (returned == incoming) is kept


def test_request_id_is_also_set_on_errors(client):
    response = client.get("/nope", headers={"X-Request-ID": "trace-404"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "trace-404"


def metric(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_records_http_and_business_metrics(client, image_path):
    ok = {"method": "POST", "route": "/object-count", "status": "200"}
    requests_before = metric("http_requests_total", **ok)
    cats_before = metric("objects_counted_total", object_class="cat")
    unmatched_before = metric("http_requests_total", method="GET", route="unmatched", status="404")

    count_image(client, image_path)
    client.get("/no/such/path")

    assert metric("http_requests_total", **ok) == requests_before + 1
    assert metric("objects_counted_total", object_class="cat") == cats_before + 1
    # Unknown URLs share one label value, so random paths can't create new time series.
    assert (
        metric("http_requests_total", method="GET", route="unmatched", status="404")
        == unmatched_before + 1
    )


def test_metrics_endpoint_serves_the_prometheus_format(client, image_path):
    count_image(client, image_path)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    text = response.get_data(as_text=True)
    assert 'detector_requests_total{model="ssd_mobilenet_v2",outcome="ok",version="latest"}' in text
    assert "http_request_duration_seconds_bucket" in text


def test_metrics_report_drift_against_the_baseline(monkeypatch, tmp_path, image_path):
    from counter.monitoring.baseline import Baseline, save_baseline
    from counter.monitoring.drift import distributions
    from tests.monitoring.helpers import confident_cats

    monkeypatch.setenv("BASELINES_DIR", str(tmp_path))
    monkeypatch.setenv("DRIFT_MIN_IMAGES", "1")
    monkeypatch.setenv("DRIFT_CACHE_SECONDS", "0")
    save_baseline(
        Baseline("ssd_mobilenet_v2", "latest", "t", "test", distributions(confident_cats(20))),
        tmp_path,
    )

    with create_app().test_client() as client:
        count_image(client, image_path)
        text = client.get("/metrics").get_data(as_text=True)

    for feature in ("scores", "detections", "classes"):
        assert (
            f'model_drift_psi{{feature="{feature}",model="ssd_mobilenet_v2",version="latest"}}'
            in text
        )
    assert 'model_drift_window_images{model="ssd_mobilenet_v2",version="latest"} 1.0' in text
    assert 'model_drift_window_images{model="acme_shelf_detector"' not in text  # no baseline


def dog_detector():
    detector = Mock()
    detector.predict.return_value = [Prediction("dog", 0.9, Box(0, 0, 1, 1))]
    return detector


def release_app(mode, candidate, canary_percent=100.0):
    """Serves model "m": champion v1 (always a cat), candidate v2 released in the given mode."""
    detectors = DetectorRegistry(
        [ServedModel("m", "1", FakeObjectDetector(), Candidate("2", candidate))], "m"
    )
    release = ReleaseSettings(mode, canary_percent, shadow_workers=1, shadow_max_pending=4)
    return create_app(detectors=detectors, count_repo=CountInMemoryRepo(), release=release)


def detector_calls(version, outcome="ok"):
    labels = {"model": "m", "version": version, "outcome": outcome}
    return REGISTRY.get_sample_value("detector_requests_total", labels) or 0.0


def test_without_a_release_mode_the_candidate_is_not_used(image_path):
    candidate = dog_detector()
    app = release_app("off", candidate)

    with app.test_client() as client:
        response = post(client, "/object-predictions", {"file": image_file(image_path)})
        models = client.get("/models").get_json()

    assert response.get_json()["model"] == {"name": "m", "version": "1"}
    assert models["models"] == [{"name": "m", "version": "1"}]
    candidate.predict.assert_not_called()


@pytest.mark.parametrize("path", ENDPOINTS)
def test_shadow_answers_with_the_champion_and_calls_the_candidate(image_path, path):
    candidate = dog_detector()
    app = release_app("shadow", candidate)
    before = detector_calls("2")

    with app.test_client() as client:
        response = post(client, path, {"threshold": "0.5", "file": image_file(image_path)})
    app.extensions["shadow_pool"].shutdown()

    body = response.get_json()
    assert body["model"] == {"name": "m", "version": "1"}
    assert "dog" not in str(body)
    candidate.predict.assert_called_once()
    assert detector_calls("2") == before + 1  # recorded under the candidate's version


def test_canary_answers_with_the_candidate_for_its_share(image_path):
    app = release_app("canary", dog_detector(), canary_percent=100)

    with app.test_client() as client:
        response = post(client, "/object-count", {"file": image_file(image_path)})

    assert response.get_json()["model"] == {"name": "m", "version": "2"}
    assert response.get_json()["current_objects"] == [{"object_class": "dog", "count": 1}]


def test_canary_falls_back_to_the_champion_when_the_candidate_is_down(image_path):
    candidate = Mock()
    candidate.predict.side_effect = DetectorUnavailableError("connection refused")
    app = release_app("canary", candidate, canary_percent=100)

    with app.test_client() as client:
        response = post(client, "/object-count", {"file": image_file(image_path)})

    assert response.status_code == 200
    assert response.get_json()["model"] == {"name": "m", "version": "1"}
    assert detector_calls("2", "unavailable") >= 1


@pytest.mark.parametrize(
    ("mode", "release"),
    [
        ("shadow", {"mode": "shadow", "candidate_version": "2"}),
        ("canary", {"mode": "canary", "candidate_version": "2", "canary_percent": 25.0}),
    ],
)
def test_models_and_metrics_show_the_release(mode, release):
    app = release_app(mode, dog_detector(), canary_percent=25)

    with app.test_client() as client:
        models = client.get("/models").get_json()
        text = client.get("/metrics").get_data(as_text=True)

    assert models["models"] == [{"name": "m", "version": "1", "release": release}]
    assert f'model_release_info{{mode="{mode}",model="m",role="champion",version="1"}} 1.0' in text
    assert f'model_release_info{{mode="{mode}",model="m",role="candidate",version="2"}} 1.0' in text


def test_logs_the_release_at_startup(caplog):
    with caplog.at_level(logging.INFO, logger="counter.entrypoints.webapp"):
        release_app("canary", dog_detector(), canary_percent=10)

    assert caplog.messages[0].startswith("Serving models m@1 (candidate 2, canary 10%) (default m)")
