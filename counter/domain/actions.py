from PIL import Image

from counter.debug import draw
from counter.domain.models import CountResponse, Prediction
from counter.domain.ports import ObjectCountRepo, ObjectDetector
from counter.domain.predictions import count, over_threshold, sort_by_score


class CountDetectedObjects:
    def __init__(self, object_detector: ObjectDetector, object_count_repo: ObjectCountRepo):
        self.__object_detector = object_detector
        self.__object_count_repo = object_count_repo

    def execute(self, image, threshold) -> CountResponse:
        predictions = find_valid_predictions(self.__object_detector, image, threshold)
        object_counts = count(predictions)
        self.__object_count_repo.update_values(object_counts)
        total_objects = self.__object_count_repo.read_values()
        return CountResponse(current_objects=object_counts, total_objects=total_objects)


class DetectObjects:
    def __init__(self, object_detector: ObjectDetector):
        self.__object_detector = object_detector

    def execute(self, image, threshold) -> list[Prediction]:
        predictions = find_valid_predictions(self.__object_detector, image, threshold)
        return sort_by_score(predictions)


def find_valid_predictions(object_detector: ObjectDetector, image, threshold) -> list[Prediction]:
    predictions = object_detector.predict(image)
    _debug_image(image, predictions, "all_predictions.jpg")
    valid_predictions = list(over_threshold(predictions, threshold=threshold))
    _debug_image(image, valid_predictions, f"valid_predictions_with_threshold_{threshold}.jpg")
    return valid_predictions


def _debug_image(image, predictions, image_name):
    if __debug__ and image is not None:
        image = Image.open(image)
        draw(predictions, image, image_name)
