from typing import BinaryIO

from counter.domain.errors import ValidationError
from counter.domain.models import CountResponse, ObjectCount, Prediction
from counter.domain.ports import DebugImageWriter, ObjectCountRepo, ObjectDetector
from counter.domain.predictions import count, over_threshold, sort_by_score


class CountDetectedObjects:
    def __init__(
        self,
        object_detector: ObjectDetector,
        object_count_repo: ObjectCountRepo,
        debug_image_writer: DebugImageWriter | None = None,
    ) -> None:
        self.__object_detector = object_detector
        self.__object_count_repo = object_count_repo
        self.__debug_image_writer = debug_image_writer

    def execute(self, image: BinaryIO, threshold: float) -> CountResponse:
        predictions = find_valid_predictions(
            self.__object_detector, image, threshold, self.__debug_image_writer
        )
        object_counts = count(predictions)
        self.__object_count_repo.update_values(object_counts)
        total_objects = self.__object_count_repo.read_values()
        return CountResponse(current_objects=object_counts, total_objects=total_objects)


class DetectObjects:
    def __init__(
        self,
        object_detector: ObjectDetector,
        debug_image_writer: DebugImageWriter | None = None,
    ) -> None:
        self.__object_detector = object_detector
        self.__debug_image_writer = debug_image_writer

    def execute(self, image: BinaryIO, threshold: float) -> list[Prediction]:
        predictions = find_valid_predictions(
            self.__object_detector, image, threshold, self.__debug_image_writer
        )
        return sort_by_score(predictions)


class ReadObjectCounts:
    def __init__(self, object_count_repo: ObjectCountRepo) -> None:
        self.__object_count_repo = object_count_repo

    def execute(self, object_classes: list[str] | None = None) -> list[ObjectCount]:
        """Totals for these classes (None: all), sorted by class; uncounted ones are left out."""
        counts = self.__object_count_repo.read_values(object_classes)
        return sorted(counts, key=lambda object_count: object_count.object_class)


def check_threshold(threshold: float) -> None:
    """Business rule for every driving adapter: a threshold is a score, so it lies in [0, 1]
    (NaN fails too). Checked before the detector is called."""
    if not 0.0 <= threshold <= 1.0:
        raise ValidationError("threshold", "must be between 0.0 and 1.0")


def find_valid_predictions(
    object_detector: ObjectDetector,
    image: BinaryIO,
    threshold: float,
    debug_image_writer: DebugImageWriter | None = None,
) -> list[Prediction]:
    check_threshold(threshold)
    predictions = object_detector.predict(image)
    valid_predictions = list(over_threshold(predictions, threshold=threshold))
    if debug_image_writer is not None:
        debug_image_writer.write(image, predictions, "all_predictions.jpg")
        debug_image_writer.write(
            image, valid_predictions, f"valid_predictions_with_threshold_{threshold}.jpg"
        )
    return valid_predictions
