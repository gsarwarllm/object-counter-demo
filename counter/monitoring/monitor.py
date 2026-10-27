import logging
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

from counter.domain.ports import PredictionLog
from counter.monitoring.baseline import load_baseline
from counter.monitoring.drift import DriftReport, compare, distributions

logger = logging.getLogger(__name__)


class DriftMonitor:
    """Compares each served model version's recent predictions with its reference baseline.

    Results are cached for `cache_seconds`, so Prometheus scrapes don't re-read the log each
    time. Versions without a baseline file are skipped (run `make baseline`).
    """

    def __init__(
        self,
        prediction_log: PredictionLog,
        models: list[tuple[str, str]],
        baselines_dir: Path,
        window: timedelta = timedelta(hours=24),
        min_images: int = 30,
        cache_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.__log = prediction_log
        self.__models = models
        self.__baselines_dir = baselines_dir
        self.__window = window
        self.__min_images = min_images
        self.__cache_seconds = cache_seconds
        self.__clock = clock
        self.__lock = threading.Lock()
        self.__cached: list[DriftReport] = []
        self.__cached_at: float | None = None

    def reports(self) -> list[DriftReport]:
        with self.__lock:
            now = self.__clock()
            if self.__cached_at is None or now - self.__cached_at >= self.__cache_seconds:
                self.__cached = self.__compute()
                self.__cached_at = now
            return self.__cached

    def __compute(self) -> list[DriftReport]:
        since = datetime.now(UTC) - self.__window
        reports = []
        for model, version in self.__models:
            baseline = load_baseline(self.__baselines_dir, model, version)
            if baseline is None:
                continue
            try:
                records = self.__log.read(model, version, since)
            except Exception as error:  # the log store may be down; keep serving /metrics
                logger.warning("Drift check for %s@%s failed: %s", model, version, error)
                continue
            reports.append(
                compare(
                    model,
                    version,
                    baseline.distributions,
                    distributions(records),
                    self.__min_images,
                )
            )
        return reports


class DriftCollector(Collector):
    """Exposes the drift reports as Prometheus gauges when /metrics is scraped."""

    def __init__(self, monitor: DriftMonitor) -> None:
        self.__monitor = monitor

    def collect(self) -> Iterable[Metric]:
        psi = GaugeMetricFamily(
            "model_drift_psi",
            "Population Stability Index of a model version's recent predictions against its "
            "baseline (0.1 moderate, 0.25 drift)",
            labels=["model", "version", "feature"],
        )
        window = GaugeMetricFamily(
            "model_drift_window_images",
            "Images in the drift window (no PSI is reported below DRIFT_MIN_IMAGES)",
            labels=["model", "version"],
        )
        for report in self.__monitor.reports():
            window.add_metric([report.model, report.version], report.window_images)
            for feature in report.features:
                if feature.psi is not None:
                    psi.add_metric([report.model, report.version, feature.feature], feature.psi)
        yield psi
        yield window
