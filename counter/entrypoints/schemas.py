from collections.abc import Mapping
from dataclasses import asdict, dataclass
from io import BytesIO

from PIL import Image
from werkzeug.datastructures import FileStorage, MultiDict

from counter.adapters.detector_registry import DetectorRegistry
from counter.domain.errors import InvalidImageError, ValidationError
from counter.domain.models import CountResponse, ObjectCount, Prediction

DEFAULT_THRESHOLD = 0.5
ACCEPTED_IMAGE_FORMATS = {"JPEG", "PNG"}


@dataclass
class ImageRequest:
    image: BytesIO
    threshold: float
    model_name: str | None


def parse_image_request(
    form: Mapping[str, str], files: Mapping[str, FileStorage], model_names: list[str]
) -> ImageRequest:
    """Validates the multipart form shared by /object-count and /object-predictions.

    model_name is optional (None means the default model) and must be one of model_names.
    """
    return ImageRequest(
        image=_parse_image(files),
        threshold=_parse_threshold(form),
        model_name=_parse_model_name(form, model_names),
    )


def parse_object_classes(args: MultiDict[str, str]) -> list[str] | None:
    """The repeatable object_class query parameter of GET /object-counts; None means all."""
    object_classes = args.getlist("object_class")
    if "" in object_classes:
        raise ValidationError("object_class", "must not be empty")
    return object_classes or None


def to_model_dto(name: str, version: str | None) -> dict:
    return {"name": name, "version": version}


def to_count_response_dto(count_response: CountResponse, model: dict) -> dict:
    return {**asdict(count_response), "model": model}


def to_predictions_response_dto(
    threshold: float, predictions: list[Prediction], model: dict
) -> dict:
    return {
        "threshold": threshold,
        "count": len(predictions),
        "predictions": [asdict(prediction) for prediction in predictions],
        "model": model,
    }


def to_object_counts_response_dto(object_counts: list[ObjectCount]) -> dict:
    return {"total_objects": [asdict(object_count) for object_count in object_counts]}


def to_release_dto(mode: str, candidate_version: str, canary_percent: float) -> dict:
    release: dict = {"mode": mode, "candidate_version": candidate_version}
    if mode == "canary":
        release["canary_percent"] = canary_percent
    return release


def to_models_response_dto(
    detectors: DetectorRegistry, releases: dict[str, dict] | None = None
) -> dict:
    """releases: the shadow or canary release of a model, if one is running (X6)."""
    releases = releases or {}
    models = []
    for model in sorted(detectors.models, key=lambda model: model.name):
        dto = to_model_dto(model.name, model.version)
        if model.name in releases:
            dto["release"] = releases[model.name]
        models.append(dto)
    return {"default_model": detectors.default_model, "models": models}


def _parse_threshold(form: Mapping[str, str]) -> float:
    """Only the format; the range is a business rule, checked by the use cases."""
    raw_threshold = form.get("threshold", DEFAULT_THRESHOLD)
    try:
        return float(raw_threshold)
    except ValueError:
        raise ValidationError("threshold", "must be a number") from None


def _parse_model_name(form: Mapping[str, str], model_names: list[str]) -> str | None:
    model_name = form.get("model_name") or None
    if model_name is not None and model_name not in model_names:
        raise ValidationError(
            "model_name", f"unknown model {model_name!r}; available: {', '.join(model_names)}"
        )
    return model_name


def _parse_image(files: Mapping[str, FileStorage]) -> BytesIO:
    uploaded_file = files.get("file")
    if uploaded_file is None or uploaded_file.filename == "":
        raise ValidationError("file", "is required")
    image = BytesIO(uploaded_file.read())
    if _image_format(image) not in ACCEPTED_IMAGE_FORMATS:
        raise InvalidImageError("file must be a JPEG or PNG image")
    image.seek(0)
    return image


def _image_format(image: BytesIO) -> str | None:
    try:
        with Image.open(image) as decoded_image:
            decoded_image.verify()
            return decoded_image.format
    except (OSError, SyntaxError):
        return None
