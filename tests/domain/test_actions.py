from unittest.mock import Mock

import pytest

from counter.adapters.count_repo import CountInMemoryRepo
from counter.domain.actions import CountDetectedObjects, DetectObjects, ReadObjectCounts
from counter.domain.errors import ValidationError
from counter.domain.models import ObjectCount
from tests.domain.helpers import generate_prediction


class TestCountDetectedObjects:
    @pytest.fixture
    def object_detector(self) -> Mock:
        object_detector = Mock()
        object_detector.predict.return_value = [
            generate_prediction("cat", 0.9),
            generate_prediction("cat", 0.8),
            generate_prediction("dog", 0.8),
            generate_prediction("dog", 0.1),
            generate_prediction("rabbit", 0.9),
        ]
        return object_detector

    @pytest.fixture
    def count_object_repo(self) -> Mock:
        return Mock()

    def test_count_valid_predictions(self, object_detector, count_object_repo) -> None:
        response = CountDetectedObjects(object_detector, count_object_repo).execute(None, 0.5)
        assert sorted(response.current_objects, key=lambda x: x.object_class) == [
            ObjectCount("cat", 2),
            ObjectCount("dog", 1),
            ObjectCount("rabbit", 1),
        ]

    def test_update_count_object_repo(self, object_detector, count_object_repo):
        CountDetectedObjects(object_detector, count_object_repo).execute(None, 0)
        count_object_repo.update_values.assert_called_with(
            [ObjectCount("cat", 2), ObjectCount("dog", 2), ObjectCount("rabbit", 1)]
        )


class TestDetectObjects:
    @pytest.fixture
    def object_detector(self) -> Mock:
        object_detector = Mock()
        object_detector.predict.return_value = [
            generate_prediction("dog", 0.6),
            generate_prediction("cat", 0.4),
            generate_prediction("cat", 0.9),
            generate_prediction("rabbit", 0.5),
        ]
        return object_detector

    def test_returns_predictions_over_threshold_sorted_by_score(self, object_detector) -> None:
        predictions = DetectObjects(object_detector).execute(None, 0.5)
        assert predictions == [
            generate_prediction("cat", 0.9),
            generate_prediction("dog", 0.6),
            generate_prediction("rabbit", 0.5),
        ]

    def test_returns_empty_list_when_nothing_over_threshold(self, object_detector) -> None:
        assert DetectObjects(object_detector).execute(None, 0.95) == []


def test_debug_image_writer_gets_all_and_valid_predictions():
    detector = Mock()
    detector.predict.return_value = [
        generate_prediction("cat", 0.9),
        generate_prediction("dog", 0.1),
    ]
    writer = Mock()
    image = object()

    DetectObjects(detector, debug_image_writer=writer).execute(image, 0.5)

    assert writer.write.call_args_list[0].args == (
        image,
        detector.predict.return_value,
        "all_predictions.jpg",
    )
    assert writer.write.call_args_list[1].args == (
        image,
        [generate_prediction("cat", 0.9)],
        "valid_predictions_with_threshold_0.5.jpg",
    )


class TestReadObjectCounts:
    @pytest.fixture
    def repo(self):
        repo = CountInMemoryRepo()
        repo.update_values([ObjectCount("dog", 1), ObjectCount("cat", 3), ObjectCount("cup", 2)])
        return repo

    def test_all_totals_sorted_by_class(self, repo):
        assert ReadObjectCounts(repo).execute() == [
            ObjectCount("cat", 3),
            ObjectCount("cup", 2),
            ObjectCount("dog", 1),
        ]

    def test_only_the_requested_classes(self, repo):
        assert ReadObjectCounts(repo).execute(["dog", "cat", "unicorn"]) == [
            ObjectCount("cat", 3),
            ObjectCount("dog", 1),
        ]

    def test_never_changes_the_totals(self, repo):
        ReadObjectCounts(repo).execute()

        assert len(repo.read_values()) == 3


@pytest.mark.parametrize("threshold", [-0.1, 1.01, float("nan")])
@pytest.mark.parametrize(
    "make_action",
    [
        lambda detector: CountDetectedObjects(detector, Mock()),
        DetectObjects,
    ],
    ids=["count", "detect"],
)
def test_threshold_outside_0_and_1_is_rejected_before_detection(make_action, threshold):
    detector = Mock()

    with pytest.raises(ValidationError, match=r"threshold: must be between 0\.0 and 1\.0"):
        make_action(detector).execute(None, threshold)
    detector.predict.assert_not_called()


@pytest.mark.parametrize("threshold", [0.0, 1.0])
def test_threshold_bounds_are_allowed(threshold):
    detector = Mock()
    detector.predict.return_value = [generate_prediction("cat", 1.0)]

    assert DetectObjects(detector).execute(None, threshold)[0].class_name == "cat"
