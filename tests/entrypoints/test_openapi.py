"""Contract tests: docs/openapi.yaml is valid, matches the app's routes, and every documented
response (path + status code) is produced by a real request and matches its schema."""

import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from openapi_core import Config, OpenAPI
from openapi_core.contrib.werkzeug import WerkzeugOpenAPIRequest, WerkzeugOpenAPIResponse
from openapi_spec_validator import validate

from counter.adapters.count_repo import CountInMemoryRepo
from counter.adapters.detector_registry import DetectorRegistry, ServedModel
from counter.domain.errors import DetectorUnavailableError
from counter.entrypoints.webapp import OPENAPI_SPEC, create_app

IMAGE = Path(__file__).parents[2] / "resources" / "images" / "cat.jpg"
SPEC = yaml.safe_load(OPENAPI_SPEC.read_text())
# openapi-core only decodes application/json by default; error bodies are problem+json.
VALIDATOR = OpenAPI.from_dict(
    SPEC, config=Config(extra_media_type_deserializers={"application/problem+json": json.loads})
)
NON_API_ROUTES = {"/static/<path:filename>", "/docs/", "/docs/<path:path>", "/openapi.yaml"}


def image_form(**fields):
    return {"file": (io.BytesIO(IMAGE.read_bytes()), "cat.jpg"), **fields}


def app_with_detector(detector):
    detectors = DetectorRegistry([ServedModel("only_model", "1", detector)], "only_model")
    return create_app(detectors=detectors, count_repo=CountInMemoryRepo())


def failing_detector(error):
    detector = Mock()
    detector.predict.side_effect = error
    return detector


class BrokenRegistry(DetectorRegistry):
    """Fails while answering GET /models, to produce the documented 500."""

    @property
    def default_model(self):
        raise RuntimeError("registry broken")


def default_app(monkeypatch):
    return create_app()


def small_upload_limit_app(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")
    return create_app()


def detector_down_app(monkeypatch):
    return app_with_detector(failing_detector(DetectorUnavailableError("connection refused")))


def detector_crash_app(monkeypatch):
    return app_with_detector(failing_detector(RuntimeError("bug")))


def broken_registry_app(monkeypatch):
    registry = BrokenRegistry([ServedModel("only_model", "1", Mock())], "only_model")
    return create_app(detectors=registry, count_repo=CountInMemoryRepo())


# (method, path, expected status, app factory, form fields; None = no body)
CASES = [
    ("post", "/object-count", 200, default_app, {"threshold": "0.5"}),
    ("post", "/object-count", 400, default_app, {"threshold": "abc"}),
    ("post", "/object-count", 413, small_upload_limit_app, {}),
    ("post", "/object-count", 500, detector_crash_app, {}),
    ("post", "/object-count", 503, detector_down_app, {}),
    ("post", "/object-predictions", 200, default_app, {"threshold": "0.5"}),
    ("post", "/object-predictions", 400, default_app, {"model_name": "gpt"}),
    ("post", "/object-predictions", 413, small_upload_limit_app, {}),
    ("post", "/object-predictions", 500, detector_crash_app, {}),
    ("post", "/object-predictions", 503, detector_down_app, {}),
    ("get", "/models", 200, default_app, None),
    ("get", "/models", 500, broken_registry_app, None),
]


def test_spec_is_valid_openapi():
    validate(SPEC)


def test_spec_documents_exactly_the_api_routes():
    rules = create_app().url_map.iter_rules()
    app_routes = {
        (rule.rule, method.lower())
        for rule in rules
        if rule.rule not in NON_API_ROUTES
        for method in rule.methods - {"HEAD", "OPTIONS"}
    }
    spec_routes = {(path, method) for path, item in SPEC["paths"].items() for method in item}

    assert app_routes == spec_routes


def test_every_documented_status_code_is_tested():
    documented = {
        (method, path, int(status))
        for path, item in SPEC["paths"].items()
        for method, operation in item.items()
        for status in operation["responses"]
    }
    tested = {(method, path, status) for method, path, status, _, _ in CASES}

    assert documented == tested


@pytest.mark.parametrize(
    ("method", "path", "status", "make_app", "form"),
    CASES,
    ids=[f"{method.upper()} {path} {status}" for method, path, status, _, _ in CASES],
)
def test_response_matches_the_spec(monkeypatch, method, path, status, make_app, form):
    app = make_app(monkeypatch)
    with app.test_client() as client:
        if form is None:
            response = getattr(client, method)(path)
        else:
            response = getattr(client, method)(
                path, data=image_form(**form), content_type="multipart/form-data"
            )

    assert response.status_code == status
    VALIDATOR.validate_response(
        WerkzeugOpenAPIRequest(response.request), WerkzeugOpenAPIResponse(response)
    )


def test_spec_and_swagger_ui_are_served():
    with create_app().test_client() as client:
        spec = client.get("/openapi.yaml")
        docs = client.get("/docs/")

    assert spec.status_code == 200
    assert yaml.safe_load(spec.data) == SPEC
    assert docs.status_code == 200
    assert b"swagger-ui" in docs.data
    assert b"/openapi.yaml" in docs.data


def test_validation_catches_a_response_that_breaks_the_spec():
    """Guards the guard: a spec requiring a field the app doesn't return must fail."""
    broken_spec = yaml.safe_load(OPENAPI_SPEC.read_text())
    broken_spec["components"]["schemas"]["ModelsResponse"]["required"].append("not_returned")
    validator = OpenAPI.from_dict(broken_spec)
    with create_app().test_client() as client:
        response = client.get("/models")

    with pytest.raises(Exception, match="not_returned"):
        validator.validate_response(
            WerkzeugOpenAPIRequest(response.request), WerkzeugOpenAPIResponse(response)
        )
