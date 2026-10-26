import logging
import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from counter import config
from counter.domain.actions import CountDetectedObjects, DetectObjects
from counter.domain.errors import (
    DetectorUnavailableError,
    InvalidImageError,
    RepositoryUnavailableError,
    ValidationError,
)
from counter.entrypoints.schemas import parse_image_request, to_predictions_response_dto

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def create_app(
    count_action: CountDetectedObjects | None = None,
    detect_action: DetectObjects | None = None,
):
    """Builds the app; actions default to the ones configured by env vars (see config.py)."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = int(
        os.environ.get("MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)
    )

    if count_action is None or detect_action is None:
        object_detector = config.get_object_detector()
        count_action = count_action or config.get_count_action(object_detector)
        detect_action = detect_action or config.get_detect_action(object_detector)

    @app.route("/object-count", methods=["POST"])
    def object_count():
        image_request = parse_image_request(request.form, request.files)
        count_response = count_action.execute(image_request.image, image_request.threshold)
        return jsonify(count_response)

    @app.route("/object-predictions", methods=["POST"])
    def object_predictions():
        image_request = parse_image_request(request.form, request.files)
        predictions = detect_action.execute(image_request.image, image_request.threshold)
        return jsonify(to_predictions_response_dto(image_request.threshold, predictions))

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
