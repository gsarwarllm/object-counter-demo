from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from prometheus_client import REGISTRY

from counter import metrics
from counter.adapters.instrumented_detector import InstrumentedDetector
from counter.adapters.prediction_log import InMemoryPredictionLog
from counter.domain.errors import DetectorUnavailableError, InvalidImageError
from counter.domain.models import Box, Prediction
from counter.entrypoints import gunicorn_conf


def detector_calls(model, version, outcome):
    labels = {"model": model, "version": version, "outcome": outcome}
    return REGISTRY.get_sample_value("detector_requests_total", labels) or 0.0


def detector_timings(model, version):
    labels = {"model": model, "version": version}
    return REGISTRY.get_sample_value("detector_request_duration_seconds_count", labels) or 0.0


@pytest.mark.parametrize(
    ("failure", "outcome"),
    [
        (None, "ok"),
        (DetectorUnavailableError("down"), "unavailable"),
        (InvalidImageError("bad"), "invalid_image"),
        (RuntimeError("bug"), "error"),
    ],
)
def test_records_outcome_and_duration_per_model_version(failure, outcome):
    detector = Mock()
    detector.predict.side_effect = failure
    instrumented = InstrumentedDetector(detector, "metrics_test_model", "4")
    calls, timings = (
        detector_calls("metrics_test_model", "4", outcome),
        detector_timings("metrics_test_model", "4"),
    )

    if failure is None:
        assert instrumented.predict(Mock()) is detector.predict.return_value
    else:
        with pytest.raises(type(failure)):
            instrumented.predict(Mock())

    assert detector_calls("metrics_test_model", "4", outcome) == calls + 1
    assert detector_timings("metrics_test_model", "4") == timings + 1


def test_unpinned_version_is_labelled_latest():
    InstrumentedDetector(Mock(), "metrics_dev_model", None).predict(Mock())

    assert detector_calls("metrics_dev_model", "latest", "ok") >= 1


def test_readiness_is_delegated():
    detector = Mock()
    detector.check_ready.side_effect = DetectorUnavailableError("LOADING")

    with pytest.raises(DetectorUnavailableError):
        InstrumentedDetector(detector, "m", "1").check_ready()


def test_render_uses_the_process_registry_by_default(monkeypatch):
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)

    body, content_type = metrics.render()

    assert b"# TYPE http_requests_total counter" in body
    assert content_type.startswith("text/plain")


def test_render_aggregates_worker_files_in_multiprocess_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))

    body, _ = metrics.render()

    assert b"http_requests_total" not in body  # nothing in the (empty) shared directory yet


def test_gunicorn_starts_with_an_empty_metrics_directory(monkeypatch, tmp_path):
    directory = tmp_path / "prometheus"
    directory.mkdir()
    (directory / "counter_123.db").write_bytes(b"stale")
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(directory))

    gunicorn_conf.on_starting(server=None)
    gunicorn_conf.child_exit(server=None, worker=SimpleNamespace(pid=123))

    assert directory.is_dir()
    assert list(directory.iterdir()) == []


def test_gunicorn_hooks_do_nothing_without_multiprocess_mode(monkeypatch):
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)

    gunicorn_conf.on_starting(server=None)
    gunicorn_conf.child_exit(server=None, worker=SimpleNamespace(pid=123))


def test_logs_every_prediction_of_a_successful_call():
    detector = Mock()
    detector.predict.return_value = [
        Prediction("cat", 0.9, Box(0, 0, 1, 1)),
        Prediction("dog", 0.1, Box(0, 0, 1, 1)),
    ]
    log = InMemoryPredictionLog()

    image = (Path(__file__).parents[1] / "resources" / "images" / "cat.jpg").open("rb")

    InstrumentedDetector(detector, "logged_model", None, log).predict(image)

    (logged,) = log.read("logged_model", "latest", datetime.now(UTC) - timedelta(minutes=1))
    assert (logged.scores, logged.classes) == ([0.9, 0.1], ["cat", "dog"])
    assert (logged.image.width, logged.image.height, logged.image.color_mode) == (640, 361, "RGB")


def test_failed_calls_are_not_logged():
    detector = Mock()
    detector.predict.side_effect = DetectorUnavailableError("down")
    log = InMemoryPredictionLog()

    with pytest.raises(DetectorUnavailableError):
        InstrumentedDetector(detector, "logged_model", "1", log).predict(Mock())

    assert log.read("logged_model", "1", datetime.now(UTC) - timedelta(minutes=1)) == []
