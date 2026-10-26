import logging
import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from counter import config
from counter.adapters.detector_registry import DetectorRegistry
from counter.domain.actions import CountDetectedObjects, DetectObjects
from counter.domain.errors import (
    DetectorUnavailableError,
    InvalidImageError,
    RepositoryUnavailableError,
    ValidationError,
)
from counter.domain.ports import ObjectCountRepo
from counter.entrypoints.schemas import (
    parse_image_request,
    to_count_response_dto,
    to_model_dto,
    to_models_response_dto,
    to_predictions_response_dto,
)

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def create_app(
    detectors: DetectorRegistry | None = None,
    count_repo: ObjectCountRepo | None = None,
):
    """Builds the app; dependencies default to the ones configured by env vars (config.py)."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = int(
        os.environ.get("MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)
    )
    detectors = detectors or config.get_detector_registry()
    count_repo = count_repo or config.get_count_repo()
    debug_image_writer = config.get_debug_image_writer()

    # One pair of use cases per model; all models share the count store.
    count_actions = {
        model.name: CountDetectedObjects(model.detector, count_repo, debug_image_writer)
        for model in detectors.models
    }
    detect_actions = {
        model.name: DetectObjects(model.detector, debug_image_writer) for model in detectors.models
    }

    @app.route("/object-count", methods=["POST"])
    def object_count():
        image_request = parse_image_request(request.form, request.files, detectors.names)
        model = detectors.get(image_request.model_name)
        count_response = count_actions[model.name].execute(
            image_request.image, image_request.threshold
        )
        return jsonify(
            to_count_response_dto(count_response, to_model_dto(model.name, model.version))
        )

    @app.route("/object-predictions", methods=["POST"])
    def object_predictions():
        image_request = parse_image_request(request.form, request.files, detectors.names)
        model = detectors.get(image_request.model_name)
        predictions = detect_actions[model.name].execute(
            image_request.image, image_request.threshold
        )
        return jsonify(
            to_predictions_response_dto(
                image_request.threshold, predictions, to_model_dto(model.name, model.version)
            )
        )

    @app.route("/models", methods=["GET"])
    def list_models():
        return jsonify(to_models_response_dto(detectors))

    register_error_handlers(app)
    return app


def register_error_handlers(app: Flask):
    """Every error leaves as RFC 7807 problem+json (status codes in plan.md section 5.3)."""

    @app.errorhandler(ValidationError)
    def handle_validation_error(error):
        return problem_response(
            400,
            "Invalid request",
            "Request validation failed",
            errors=[{"field": error.field, "message": error.message}],
        )

    @app.errorhandler(InvalidImageError)
    def handle_invalid_image_error(error):
        return problem_response(400, "Invalid image", str(error))

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(error):
        limit = app.config["MAX_CONTENT_LENGTH"]
        return problem_response(413, "Payload too large", f"Uploads are limited to {limit} bytes")

    @app.errorhandler(DetectorUnavailableError)
    def handle_detector_unavailable(error):
        app.logger.error("Object detector unavailable: %s", error)
        return problem_response(
            503, "Object detector unavailable", "The object detector is unavailable"
        )

    @app.errorhandler(RepositoryUnavailableError)
    def handle_repository_unavailable(error):
        app.logger.error("Count repository unavailable: %s", error)
        return problem_response(
            503, "Count repository unavailable", "The count store is unavailable"
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        return problem_response(error.code, error.name, error.description)

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.exception("Unhandled error")
        return problem_response(500, "Internal server error", "An unexpected error occurred")


def problem_response(status, title, detail, errors=None):
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
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    # Localhost and no debugger by default; containers set HOST=0.0.0.0.
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
