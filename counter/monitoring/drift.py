"""Prediction and input-data drift, measured with the Population Stability Index (PSI).

Prediction features describe what a model returns, independent of the caller's threshold:
- scores: the distribution of every score the model returned (10 bins over [0, 1])
- detections: detections per image at REFERENCE_THRESHOLD (0, 1, 2, 3, 4, 5-9, 10+)
- classes: how often each class is detected at REFERENCE_THRESHOLD

Input features describe the uploaded images, and change before the predictions do when a camera,
compression setting or client changes: aspect_ratio, megapixels, brightness, contrast and
color_mode. Records without image statistics don't count for them.

PSI = sum((actual - expected) * ln(actual / expected)) over the bins' proportions. The usual
reading: below 0.1 stable, 0.1 to 0.25 moderate change, 0.25 or more significant drift.
"""

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from counter.domain.models import PredictionRecord

REFERENCE_THRESHOLD = 0.5
SCORE_BIN_EDGES = [i / 10 for i in range(11)]
DETECTION_BIN_LABELS = ["0", "1", "2", "3", "4", "5-9", "10+"]
ASPECT_RATIO_EDGES = [0.0, 0.5, 0.75, 0.9, 1.1, 1.4, 1.8, 2.5]  # width / height
MEGAPIXEL_EDGES = [0.0, 0.1, 0.3, 1.0, 2.0, 5.0, 12.0]
BRIGHTNESS_EDGES = [0.0, 32.0, 64.0, 96.0, 128.0, 160.0, 192.0, 224.0]  # mean luminance
CONTRAST_EDGES = [0.0, 16.0, 32.0, 48.0, 64.0, 80.0, 96.0]  # luminance standard deviation
MODERATE_PSI = 0.1
DRIFT_PSI = 0.25
# Keeps empty bins from making PSI infinite.
EPSILON = 1e-4
PREDICTION_FEATURES = ("scores", "detections", "classes")
INPUT_FEATURES = ("aspect_ratio", "megapixels", "brightness", "contrast", "color_mode")
FEATURES = PREDICTION_FEATURES + INPUT_FEATURES


@dataclass
class Distributions:
    """Bin counts of the three features over a set of images (one record per image)."""

    images: int = 0
    scores: list[int] = field(default_factory=lambda: [0] * (len(SCORE_BIN_EDGES) - 1))
    detections: list[int] = field(default_factory=lambda: [0] * len(DETECTION_BIN_LABELS))
    classes: dict[str, int] = field(default_factory=dict)
    # Input features; their defaults keep baselines written before X4 loadable.
    input_images: int = 0
    aspect_ratio: list[int] = field(default_factory=lambda: [0] * len(ASPECT_RATIO_EDGES))
    megapixels: list[int] = field(default_factory=lambda: [0] * len(MEGAPIXEL_EDGES))
    brightness: list[int] = field(default_factory=lambda: [0] * len(BRIGHTNESS_EDGES))
    contrast: list[int] = field(default_factory=lambda: [0] * len(CONTRAST_EDGES))
    color_mode: dict[str, int] = field(default_factory=dict)


@dataclass
class FeatureDrift:
    feature: str
    psi: float | None  # None when there's nothing to compare
    status: str  # stable | moderate | drift | insufficient_data | no_reference


@dataclass
class DriftReport:
    model: str
    version: str
    reference_images: int
    window_images: int
    features: list[FeatureDrift]

    @property
    def drifted(self) -> bool:
        return any(feature.status == "drift" for feature in self.features)


def distributions(records: Iterable[PredictionRecord]) -> Distributions:
    result = Distributions()
    class_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()
    for record in records:
        result.images += 1
        for score in record.scores:
            result.scores[_score_bin(score)] += 1
        detected = [
            class_name
            for class_name, score in zip(record.classes, record.scores, strict=True)
            if score >= REFERENCE_THRESHOLD
        ]
        result.detections[_detection_bin(len(detected))] += 1
        class_counts.update(detected)
        if (stats := record.image) is not None:
            result.input_images += 1
            result.aspect_ratio[_bin(stats.width / max(stats.height, 1), ASPECT_RATIO_EDGES)] += 1
            result.megapixels[_bin(stats.width * stats.height / 1e6, MEGAPIXEL_EDGES)] += 1
            result.brightness[_bin(stats.brightness, BRIGHTNESS_EDGES)] += 1
            result.contrast[_bin(stats.contrast, CONTRAST_EDGES)] += 1
            mode_counts[stats.color_mode] += 1
    result.classes = dict(class_counts)
    result.color_mode = dict(mode_counts)
    return result


def psi(expected: Sequence[float], actual: Sequence[float]) -> float:
    """PSI between two histograms over the same bins (counts or proportions)."""
    expected_total, actual_total = sum(expected), sum(actual)
    if expected_total == 0 or actual_total == 0:
        return 0.0
    value = 0.0
    for expected_count, actual_count in zip(expected, actual, strict=True):
        e = max(expected_count / expected_total, EPSILON)
        a = max(actual_count / actual_total, EPSILON)
        value += (a - e) * math.log(a / e)
    return value


def compare(
    model: str,
    version: str,
    reference: Distributions,
    window: Distributions,
    min_images: int,
) -> DriftReport:
    features = [
        _feature(name, reference, window, reference.images, window.images, min_images)
        for name in PREDICTION_FEATURES
    ] + [
        _feature(name, reference, window, reference.input_images, window.input_images, min_images)
        for name in INPUT_FEATURES
    ]
    return DriftReport(model, version, reference.images, window.images, features)


def _feature(
    name: str,
    reference: Distributions,
    window: Distributions,
    reference_images: int,
    window_images: int,
    min_images: int,
) -> FeatureDrift:
    if reference_images == 0:
        return FeatureDrift(name, None, "no_reference")
    if window_images < min_images:
        return FeatureDrift(name, None, "insufficient_data")
    expected, actual = getattr(reference, name), getattr(window, name)
    if isinstance(expected, dict):  # categories: compare over the union of both sides
        categories = sorted(set(expected) | set(actual))
        expected = [expected.get(category, 0) for category in categories]
        actual = [actual.get(category, 0) for category in categories]
    value = psi(expected, actual)
    return FeatureDrift(name, round(value, 4), _status(value))


def _bin(value: float, edges: list[float]) -> int:
    """Index of the last edge at or below value; values above the last edge go in its bin."""
    index = 0
    for i, edge in enumerate(edges):
        if value >= edge:
            index = i
    return index


def _score_bin(score: float) -> int:
    return min(int(score * 10), 9) if score > 0 else 0


def _detection_bin(count: int) -> int:
    if count >= 10:
        return 6
    if count >= 5:
        return 5
    return count


def _status(value: float) -> str:
    if value >= DRIFT_PSI:
        return "drift"
    if value >= MODERATE_PSI:
        return "moderate"
    return "stable"
