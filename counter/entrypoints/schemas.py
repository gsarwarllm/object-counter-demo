from dataclasses import asdict, dataclass
from io import BytesIO

from PIL import Image

from counter.domain.errors import InvalidImageError, ValidationError
from counter.domain.models import Prediction

DEFAULT_THRESHOLD = 0.5
ACCEPTED_IMAGE_FORMATS = {"JPEG", "PNG"}


@dataclass
class PredictionsRequest:
    image: BytesIO
    threshold: float


def parse_predictions_request(form, files) -> PredictionsRequest:
    return PredictionsRequest(image=_parse_image(files), threshold=_parse_threshold(form))


def to_predictions_response_dto(threshold: float, predictions: list[Prediction]) -> dict:
    return {
        "threshold": threshold,
        "count": len(predictions),
        "predictions": [asdict(prediction) for prediction in predictions],
    }


def _parse_threshold(form) -> float:
    raw_threshold = form.get("threshold", DEFAULT_THRESHOLD)
    try:
        threshold = float(raw_threshold)
    except ValueError:
        raise ValidationError("threshold", "must be a number") from None
    if not 0.0 <= threshold <= 1.0:
        raise ValidationError("threshold", "must be between 0.0 and 1.0")
    return threshold


def _parse_image(files) -> BytesIO:
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
