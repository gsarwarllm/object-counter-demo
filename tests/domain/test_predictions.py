from counter.domain.models import ObjectCount
from counter.domain.predictions import over_threshold, count, sort_by_score
from tests.domain.helpers import generate_prediction


def test_filter_predictions_over_threshold() -> None:
    predictions = [generate_prediction('dog', 0.9),
                   generate_prediction('cat', 0.8),
                   generate_prediction('cat', 0.91)]
    good_predictions = over_threshold(predictions, 0.9)
    assert list(good_predictions) == [generate_prediction('dog', 0.9), generate_prediction('cat', 0.91)]


def test_count_predictions_by_class() -> None:
    predictions = [generate_prediction('cat'),
                   generate_prediction('cat'),
                   generate_prediction('dog')]
    object_counts = count(predictions)
    assert sorted(object_counts, key=lambda x: x.object_class) == \
        [ObjectCount(object_class='cat', count=2), ObjectCount(object_class='dog', count=1)]


def test_sort_predictions_by_score_descending() -> None:
    predictions = [generate_prediction('cat', 0.5),
                   generate_prediction('dog', 0.9),
                   generate_prediction('cup', 0.7)]
    assert sort_by_score(predictions) == [generate_prediction('dog', 0.9),
                                          generate_prediction('cup', 0.7),
                                          generate_prediction('cat', 0.5)]


def test_sort_predictions_keeps_input_order_on_ties() -> None:
    predictions = [generate_prediction('cat', 0.8), generate_prediction('dog', 0.8)]
    assert sort_by_score(predictions) == predictions


def test_sort_empty_predictions() -> None:
    assert sort_by_score([]) == []
