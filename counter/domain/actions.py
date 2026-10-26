from typing import BinaryIO

from counter.domain.models import CountResponse, Prediction
from counter.domain.ports import DebugImageWriter, ObjectCountRepo, ObjectDetector
from counter.domain.predictions import count, over_threshold, sort_by_score


class CountDetectedObjects:
    def __init__(
        self,
        object_detector: ObjectDetector,
        object_count_repo: ObjectCountRepo,
        debug_image_writer: DebugImageWriter | None = None,
    ):
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
    ):
        self.__object_detector = object_detector
        self.__debug_image_writer = debug_image_writer

    def execute(self, image: BinaryIO, threshold: float) -> list[Prediction]:
        predictions = find_valid_predictions(
            self.__object_detector, image, threshold, self.__debug_image_writer
        )
        return sort_by_score(predictions)


def find_valid_predictions(
    object_detector: ObjectDetector,
    image: BinaryIO,
    threshold: float,
    debug_image_writer: DebugImageWriter | None = None,
) -> list[Prediction]:
    predictions = object_detector.predict(image)
    valid_predictions = list(over_threshold(predictions, threshold=threshold))
    if debug_image_writer is not None:
        debug_image_writer.write(image, predictions, "all_predictions.jpg")
        debug_image_writer.write(
            image, valid_predictions, f"valid_predictions_with_threshold_{threshold}.jpg"
        )
    return valid_predictions
