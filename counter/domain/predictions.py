from collections import Counter
from collections.abc import Iterator

from counter.domain.models import ObjectCount, Prediction


def over_threshold(predictions: list[Prediction], threshold: float) -> Iterator[Prediction]:
    return filter(lambda prediction: prediction.score >= threshold, predictions)


def sort_by_score(predictions: list[Prediction]) -> list[Prediction]:
    return sorted(predictions, key=lambda prediction: prediction.score, reverse=True)


def count(predictions: list[Prediction]) -> list[ObjectCount]:
    object_classes = Counter(prediction.class_name for prediction in predictions)
    return [
        ObjectCount(object_class, occurrences)
        for object_class, occurrences in object_classes.items()
    ]
