from functools import reduce

from counter.domain.models import ObjectCount, Prediction


def over_threshold(predictions: list[Prediction], threshold: float):
    return filter(lambda prediction: prediction.score >= threshold, predictions)


def sort_by_score(predictions: list[Prediction]) -> list[Prediction]:
    return sorted(predictions, key=lambda prediction: prediction.score, reverse=True)


def count(predictions: list[Prediction]) -> list[ObjectCount]:
    object_classes = (prediction.class_name for prediction in predictions)
    object_classes_counter = reduce(__count_object_classes, object_classes, {})
    return [
        ObjectCount(object_class, occurrences)
        for object_class, occurrences in object_classes_counter.items()
    ]


def __count_object_classes(class_counter: dict, object_class: str):
    class_counter[object_class] = class_counter.get(object_class, 0) + 1
    return class_counter
