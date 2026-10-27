import pytest

from counter.monitoring.drift import (
    INPUT_FEATURES,
    PREDICTION_FEATURES,
    Distributions,
    compare,
    distributions,
    psi,
)
from tests.monitoring.helpers import (
    confident_cats,
    daylight_uploads,
    photo,
    record,
    unsure_model,
)


def test_distributions_bin_scores_detections_and_classes():
    result = distributions(
        [
            record([0.95, 0.5, 0.49, 0.0], ["cat", "dog", "cup", "cup"]),
            record([1.0] * 12, ["person"] * 12),
            record([], []),
        ]
    )

    assert result.images == 3
    assert result.scores == [1, 0, 0, 0, 1, 1, 0, 0, 0, 13]  # 0.0 in bin 0, 1.0 in the last
    assert result.detections == [1, 0, 1, 0, 0, 0, 1]  # 0, 2 and 10+ at the 0.5 threshold
    assert result.classes == {"cat": 1, "dog": 1, "person": 12}


def test_psi_is_zero_for_the_same_distribution_whatever_the_volume():
    assert psi([10, 20, 70], [1, 2, 7]) == pytest.approx(0.0)


def test_psi_grows_with_the_shift():
    small = psi([50, 50], [55, 45])
    large = psi([50, 50], [90, 10])

    assert 0 < small < 0.1 <= 0.25 <= large


def test_psi_handles_empty_bins_and_empty_histograms():
    assert psi([10, 0], [0, 10]) > 0.25  # finite, thanks to the epsilon
    assert psi([0, 0], [1, 1]) == 0.0


def test_same_behaviour_is_stable():
    report = compare(
        "m", "1", distributions(confident_cats(50)), distributions(confident_cats(40)), 30
    )

    assert [(f.feature, f.status) for f in report.features[:3]] == [
        ("scores", "stable"),
        ("detections", "stable"),
        ("classes", "stable"),
    ]
    assert not report.drifted


def test_a_model_losing_confidence_drifts_in_scores_and_detections():
    report = compare(
        "m", "1", distributions(confident_cats(50)), distributions(unsure_model(40)), 30
    )

    statuses = {feature.feature: feature.status for feature in report.features}
    assert statuses["scores"] == "drift"
    assert statuses["detections"] == "drift"  # 2 cats per image became 1
    assert report.drifted
    assert (report.reference_images, report.window_images) == (50, 40)


def test_new_classes_count_as_class_drift():
    reference = distributions(confident_cats(50))
    window = distributions([record([0.9, 0.9], ["truck", "truck"]) for _ in range(40)])

    classes = compare("m", "1", reference, window, 30).features[2]

    assert classes.status == "drift"


def test_too_few_images_are_not_judged():
    report = compare(
        "m", "1", distributions(confident_cats(50)), distributions(unsure_model(5)), 30
    )

    statuses = {feature.feature: feature.status for feature in report.features}
    assert {statuses[name] for name in PREDICTION_FEATURES} == {"insufficient_data"}
    assert {feature.psi for feature in report.features} == {None}
    assert not report.drifted


def test_reports_every_feature_in_a_fixed_order():
    report = compare("m", "1", Distributions(), Distributions(), 30)

    assert [feature.feature for feature in report.features] == [
        *PREDICTION_FEATURES,
        *INPUT_FEATURES,
    ]
    assert {feature.status for feature in report.features} == {"no_reference"}


def test_image_statistics_are_binned():
    result = distributions(
        [
            record([0.9], image=photo(640, 480, "RGB", brightness=10, contrast=100)),
            record([0.9], image=photo(4000, 3000, "L", brightness=250, contrast=5)),
            record([0.9]),  # no statistics: counts for predictions only
        ]
    )

    assert (result.images, result.input_images) == (3, 2)
    assert result.aspect_ratio == [0, 0, 0, 0, 2, 0, 0, 0]  # both 4:3 (1.33), in [1.1, 1.4)
    assert result.megapixels == [0, 0, 1, 0, 0, 0, 1]  # 0.31 MP in [0.3, 1), 12 MP in 12+
    assert result.brightness == [1, 0, 0, 0, 0, 0, 0, 1]
    assert result.contrast == [1, 0, 0, 0, 0, 0, 1]
    assert result.color_mode == {"RGB": 1, "L": 1}


def input_statuses(window):
    report = compare("m", "1", distributions(daylight_uploads(50)), distributions(window), 30)
    return {f.feature: f.status for f in report.features if f.feature in INPUT_FEATURES}


def test_same_uploads_are_stable():
    assert set(input_statuses(daylight_uploads(40)).values()) == {"stable"}


def test_a_new_camera_drifts_in_size_and_brightness_but_not_predictions_yet():
    """A client switched to dark, high-resolution, portrait images; the model still answers."""
    window = [record([0.9], image=photo(3000, 4000, brightness=40, contrast=20)) for _ in range(40)]

    statuses = input_statuses(window)

    assert statuses["aspect_ratio"] == statuses["megapixels"] == "drift"
    assert statuses["brightness"] == statuses["contrast"] == "drift"
    assert statuses["color_mode"] == "stable"


def test_greyscale_uploads_drift_in_color_mode():
    window = [record([0.9], image=photo(mode="L")) for _ in range(40)]

    assert input_statuses(window)["color_mode"] == "drift"


def test_baselines_without_image_statistics_have_no_input_reference():
    report = compare(
        "m", "1", distributions(confident_cats(50)), distributions(daylight_uploads(40)), 30
    )

    statuses = {feature.feature: feature.status for feature in report.features}
    assert {statuses[name] for name in INPUT_FEATURES} == {"no_reference"}
