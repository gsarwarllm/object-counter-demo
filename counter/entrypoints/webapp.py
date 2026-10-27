import logging
import os
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from flask import Flask, Response, g, jsonify, request, send_file
from flask_swagger_ui import get_swaggerui_blueprint
from prometheus_client.registry import Collector
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from counter import config, metrics
from counter.adapters.detector_registry import DetectorRegistry
from counter.adapters.instrumented_detector import InstrumentedDetector
from counter.adapters.shadow_detector import ShadowDetector, ShadowPool
from counter.domain.actions import CountDetectedObjects, DetectObjects, ReadObjectCounts
from counter.domain.errors import (
    DetectorUnavailableError,
    InvalidImageError,
    RepositoryUnavailableError,
    ValidationError,
)
from counter.domain.ports import ObjectCountRepo, ObjectDetector, PredictionLog
from counter.entrypoints.routing import ModelRoutes, Route
from counter.entrypoints.schemas import (
    parse_image_request,
    parse_object_classes,
    to_count_response_dto,
    to_model_dto,
    to_models_response_dto,
    to_object_counts_response_dto,
    to_predictions_response_dto,
    to_release_dto,
)
from counter.logging_config import configure_logging
from counter.monitoring.monitor import DriftCollector, DriftMonitor
from counter.monitoring.release import ReleaseCollector, ReleasedVersion

logger = logging.getLogger(__name__)

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# The API contract, written by hand (contract first) and served as-is.
OPENAPI_SPEC = Path(__file__).resolve().parents[2] / "docs" / "openapi.yaml"
REQUEST_ID_HEADER = "X-Request-ID"
# A caller's request ID is kept only if it's short and safe to log; otherwise a new one is made.
VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


def create_app(
    detectors: DetectorRegistry | None = None,
    count_repo: ObjectCountRepo | None = None,
    prediction_log: PredictionLog | None = None,
    release: config.ReleaseSettings | None = None,
) -> Flask:
    """Builds the app; dependencies default to the ones configured by env vars (config.py)."""
    configure_logging()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = int(
        os.environ.get("MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)
    )
    detectors = detectors or config.get_detector_registry()
    count_repo = count_repo or config.get_count_repo()
    debug_image_writer = config.get_debug_image_writer()
    prediction_log = prediction_log or config.get_prediction_log()

    release = release or config.get_release_settings()
    shadow_pool = ShadowPool(release.shadow_workers, release.shadow_max_pending)
    app.extensions["shadow_pool"] = shadow_pool

    # One pair of use cases per served version; all models share the count store. The detectors
    # are wrapped to record per-version metrics and log their predictions for drift monitoring.
    # A candidate version (X6) is only used in a shadow or canary release.
    def instrument(detector: ObjectDetector, name: str, version: str | None) -> ObjectDetector:
        return InstrumentedDetector(detector, name, version, prediction_log)

    def route(detector: ObjectDetector, version: str | None) -> Route:
        return Route(
            version,
            CountDetectedObjects(detector, count_repo, debug_image_writer),
            DetectObjects(detector, debug_image_writer),
        )

    routes: dict[str, ModelRoutes] = {}
    releases: dict[str, dict] = {}
    released_versions: list[ReleasedVersion] = []
    for model in detectors.models:
        champion = instrument(model.detector, model.name, model.version)
        candidate = model.candidate if release.mode != "off" else None
        mode = release.mode if candidate else "off"
        released_versions.append(
            ReleasedVersion(model.name, model.version or "latest", "champion", mode)
        )
        if candidate is None:
            routes[model.name] = ModelRoutes(model.name, route(champion, model.version))
            continue
        released_versions.append(ReleasedVersion(model.name, candidate.version, "candidate", mode))
        releases[model.name] = to_release_dto(mode, candidate.version, release.canary_percent)
        candidate_detector = instrument(candidate.detector, model.name, candidate.version)
        if mode == "shadow":
            shadowed = ShadowDetector(
                champion, candidate_detector, model.name, candidate.version, shadow_pool
            )
            routes[model.name] = ModelRoutes(model.name, route(shadowed, model.version))
        else:
            routes[model.name] = ModelRoutes(
                model.name,
                route(champion, model.version),
                route(candidate_detector, candidate.version),
                release.canary_percent,
            )

    extra_collectors: list[Collector] = [ReleaseCollector(released_versions)]
    if prediction_log is not None:
        settings = config.get_drift_settings()
        monitor = DriftMonitor(
            prediction_log,
            [(served.model, served.version) for served in released_versions],
            settings.baselines_dir,
            window=settings.window,
            min_images=settings.min_images,
            cache_seconds=settings.cache_seconds,
        )
        extra_collectors.append(DriftCollector(monitor))
    read_object_counts = ReadObjectCounts(count_repo)
    # What this process serves, so a log shows which model versions and store were in use.
    logger.info(
        "Serving models %s (default %s), env=%s, count repo=%s, prediction log=%s, debug images=%s",
        ", ".join(_describe(model.name, model.version, releases) for model in detectors.models),
        detectors.default_model,
        config.get_env(),
        type(count_repo).__name__,
        type(prediction_log).__name__ if prediction_log else "off",
        "on" if debug_image_writer else "off",
    )

    @app.route("/object-count", methods=["POST"])
    def object_count() -> Response:
        image_request = parse_image_request(request.form, request.files, detectors.names)
        model = detectors.get(image_request.model_name)
        count_response, used = routes[model.name].run(
            lambda route: route.count.execute(image_request.image, image_request.threshold)
        )
        for object_count in count_response.current_objects:
            metrics.OBJECTS_COUNTED.labels(object_count.object_class).inc(object_count.count)
        return jsonify(
            to_count_response_dto(count_response, to_model_dto(model.name, used.version))
        )

    @app.route("/object-predictions", methods=["POST"])
    def object_predictions() -> Response:
        image_request = parse_image_request(request.form, request.files, detectors.names)
        model = detectors.get(image_request.model_name)
        predictions, used = routes[model.name].run(
            lambda route: route.detect.execute(image_request.image, image_request.threshold)
        )
        return jsonify(
            to_predictions_response_dto(
                image_request.threshold, predictions, to_model_dto(model.name, used.version)
            )
        )

    @app.route("/object-counts", methods=["GET"])
    def object_counts() -> Response:
        object_counts = read_object_counts.execute(parse_object_classes(request.args))
        return jsonify(to_object_counts_response_dto(object_counts))

    @app.route("/health", methods=["GET"])
    def liveness() -> Response:
        return jsonify({"status": "ok"})

    @app.route("/health/ready", methods=["GET"])
    def readiness() -> tuple[Response, int]:
        repository = _check("count repository", count_repo.check_ready)
        detector_checks = {
            model.name: _check(f"model {model.name}", model.detector.check_ready)
            for model in detectors.models
        }
        ready = repository == "ok" and all(status == "ok" for status in detector_checks.values())
        body = {
            "status": "ok" if ready else "unavailable",
            "checks": {"repository": repository, "detectors": detector_checks},
        }
        return jsonify(body), 200 if ready else 503

    @app.route("/models", methods=["GET"])
    def list_models() -> Response:
        return jsonify(to_models_response_dto(detectors, releases))

    @app.route("/metrics", methods=["GET"])
    def prometheus_metrics() -> Response:
        body, content_type = metrics.render(extra_collectors)
        return Response(body, content_type=content_type)

    @app.route("/openapi.yaml", methods=["GET"])
    def openapi_spec() -> Response:
        return send_file(OPENAPI_SPEC, mimetype="application/yaml")

    # Swagger UI (assets bundled with flask-swagger-ui, so it works offline)
    app.register_blueprint(
        get_swaggerui_blueprint("/docs", "/openapi.yaml", config={"app_name": "Object Counter API"})
    )

    register_request_tracking(app)
    register_error_handlers(app)
    return app


def register_request_tracking(app: Flask) -> None:
    """Gives every request an ID (X-Request-ID, also in the logs) and records HTTP metrics."""

    @app.before_request
    def start_request() -> None:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        g.request_id = incoming if VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        g.started = time.perf_counter()

    @app.after_request
    def finish_request(response: Response) -> Response:
        response.headers[REQUEST_ID_HEADER] = g.get("request_id", "-")
        # The route pattern, not the URL, keeps the number of label values small.
        route = request.url_rule.rule if request.url_rule else "unmatched"
        metrics.HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        if (started := g.get("started")) is not None:
            metrics.HTTP_LATENCY.labels(request.method, route).observe(
                time.perf_counter() - started
            )
        return response


def _describe(name: str, version: str | None, releases: dict[str, dict]) -> str:
    described = f"{name}@{version or 'latest'}"
    if (release := releases.get(name)) is not None:
        described += f" (candidate {release['candidate_version']}, {release['mode']}"
        if release["mode"] == "canary":
            described += f" {release['canary_percent']:g}%"
        described += ")"
    return described


def _check(name: str, check: Callable[[], None]) -> str:
    """Runs one readiness check; the cause of a failure is logged, never returned."""
    try:
        check()
    except Exception as error:  # a readiness probe reports failures; it never fails itself
        logger.warning("Not ready: %s: %s", name, error)
        return "unavailable"
    return "ok"


def register_error_handlers(app: Flask) -> None:
    """Every error leaves as RFC 7807 problem+json (status codes in plan.md section 5.3)."""

    @app.errorhandler(ValidationError)
    def handle_validation_error(error: ValidationError) -> Response:
        return problem_response(
            400,
            "Invalid request",
            "Request validation failed",
            errors=[{"field": error.field, "message": error.message}],
        )

    @app.errorhandler(InvalidImageError)
    def handle_invalid_image_error(error: InvalidImageError) -> Response:
        return problem_response(400, "Invalid image", str(error))

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(error: RequestEntityTooLarge) -> Response:
        limit = app.config["MAX_CONTENT_LENGTH"]
        return problem_response(413, "Payload too large", f"Uploads are limited to {limit} bytes")

    @app.errorhandler(DetectorUnavailableError)
    def handle_detector_unavailable(error: DetectorUnavailableError) -> Response:
        app.logger.error("Object detector unavailable: %s", error)
        return problem_response(
            503, "Object detector unavailable", "The object detector is unavailable"
        )

    @app.errorhandler(RepositoryUnavailableError)
    def handle_repository_unavailable(error: RepositoryUnavailableError) -> Response:
        app.logger.error("Count repository unavailable: %s", error)
        return problem_response(
            503, "Count repository unavailable", "The count store is unavailable"
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException) -> Response:
        # Werkzeug types code/description as optional; its HTTP errors always set both.
        return problem_response(error.code or 500, error.name, error.description or error.name)

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception) -> Response:
        app.logger.exception("Unhandled error")
        return problem_response(500, "Internal server error", "An unexpected error occurred")


def problem_response(
    status: int, title: str, detail: str, errors: list[dict[str, str]] | None = None
) -> Response:
    body = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.path,
    }
    if errors:
        body["errors"] = errors
    response = jsonify(body)
    response.status_code = status
    response.mimetype = "application/problem+json"
    return response


if __name__ == "__main__":
    app = create_app()
    # Localhost and no debugger by default; containers set HOST=0.0.0.0.
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
