from dataclasses import dataclass
from datetime import datetime


@dataclass
class Box:
    xmin: float
    ymin: float
    xmax: float
    ymax: float


@dataclass
class Prediction:
    class_name: str
    score: float
    box: Box


@dataclass
class ObjectCount:
    object_class: str
    count: int


@dataclass
class CountResponse:
    current_objects: list[ObjectCount]
    total_objects: list[ObjectCount]


@dataclass
class ImageStats:
    """Cheap statistics of an uploaded image, for input-data drift."""

    width: int
    height: int
    color_mode: str  # the uploaded mode (RGB, RGBA, L, P, ...), before conversion to RGB
    brightness: float  # mean luminance, 0-255
    contrast: float  # standard deviation of luminance


@dataclass
class PredictionRecord:
    """What one model call saw and returned, for drift monitoring: every score and class, also
    those below the caller's threshold (a model losing confidence shows up there first), and
    the input image's statistics (None if they couldn't be computed)."""

    model: str
    version: str
    logged_at: datetime
    scores: list[float]
    classes: list[str]
    image: ImageStats | None = None
