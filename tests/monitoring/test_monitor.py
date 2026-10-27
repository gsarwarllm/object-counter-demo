import logging
from datetime import UTC, datetime, timedelta

from prometheus_client import CollectorRegistry, generate_latest

from counter.adapters.prediction_log import InMemoryPredictionLog
from counter.monitoring.baseline import Baseline, save_baseline
from counter.monitoring.drift import distributions
from counter.monitoring.monitor import DriftCollector, DriftMonitor
from tests.monitoring.helpers import confident_cats, record, unsure_model


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_monitor(tmp_path, log, **kwargs):
    save_baseline(Baseline("m", "1", "t", "test", distributions(confident_cats(50))), tmp_path)
    kwargs.setdefault("min_images", 5)
    return DriftMonitor(log, [("m", "1"), ("no_baseline", "2")], tmp_path, **kwargs)


def test_reports_drift_for_versions_with_a_baseline(tmp_path):
    log = InMemoryPredictionLog()
    for item in unsure_model(10):
        log.append(item)

    (report,) = make_monitor(tmp_path, log).reports()

    assert (report.model, report.version, report.window_images) == ("m", "1", 10)
    assert report.drifted


def test_only_the_window_and_the_version_count(tmp_path):
    log = InMemoryPredictionLog()
    old = datetime.now(UTC) - timedelta(hours=30)
    log.append(record([0.5], logged_at=old))  # outside the 24 h window
    log.append(record([0.5], version="2"))  # another version
    log.append(record([0.95]))

    (report,) = make_monitor(tmp_path, log).reports()

    assert report.window_images == 1


def test_results_are_cached(tmp_path):
    log, clock = InMemoryPredictionLog(), FakeClock()
    monitor = make_monitor(tmp_path, log, cache_seconds=60, clock=clock)
    assert monitor.reports()[0].window_images == 0

    log.append(record([0.95]))
    clock.now = 59
    assert monitor.reports()[0].window_images == 0
    clock.now = 60
    assert monitor.reports()[0].window_images == 1


def test_a_failing_log_is_skipped_and_logged(tmp_path, caplog):
    class DownLog(InMemoryPredictionLog):
        def read(self, model, version, since):
            raise OSError("connection refused")

    with caplog.at_level(logging.WARNING):
        assert make_monitor(tmp_path, DownLog()).reports() == []

    assert "Drift check for m@1 failed: connection refused" in caplog.messages


def test_collector_exposes_psi_per_feature_and_window_size(tmp_path):
    log = InMemoryPredictionLog()
    for item in unsure_model(10):
        log.append(item)
    registry = CollectorRegistry()
    registry.register(DriftCollector(make_monitor(tmp_path, log)))

    text = generate_latest(registry).decode()

    for feature in ("scores", "detections", "classes"):
        assert f'model_drift_psi{{feature="{feature}",model="m",version="1"}}' in text
    assert 'model_drift_window_images{model="m",version="1"} 10.0' in text


def test_no_psi_below_the_minimum_window(tmp_path):
    log = InMemoryPredictionLog()
    log.append(record([0.95]))
    registry = CollectorRegistry()
    registry.register(DriftCollector(make_monitor(tmp_path, log, min_images=5)))

    text = generate_latest(registry).decode()

    assert "model_drift_psi{" not in text
    assert 'model_drift_window_images{model="m",version="1"} 1.0' in text
