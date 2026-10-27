"""Prometheus metrics, served at GET /metrics.

With several gunicorn workers, each worker has its own counters. PROMETHEUS_MULTIPROC_DIR (set in
the Docker image) makes them write to a shared directory, and /metrics adds them up, so a scrape
sees the whole server whichever worker answers it.
"""

import os
from collections.abc import Iterable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)
from prometheus_client.registry import Collector

# Seconds; TF Serving calls on CPU take from tens of milliseconds to several seconds.
LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests by route and status", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["method", "route"],
    buckets=LATENCY_BUCKETS,
)
DETECTOR_REQUESTS = Counter(
    "detector_requests_total",
    "Detector calls by model, version and outcome (ok, unavailable, invalid_image, error)",
    ["model", "version", "outcome"],
)
DETECTOR_LATENCY = Histogram(
    "detector_request_duration_seconds",
    "Detector call duration, including the TF Serving round trip",
    ["model", "version"],
    buckets=LATENCY_BUCKETS,
)
OBJECTS_COUNTED = Counter(
    "objects_counted_total", "Objects added to the totals by POST /object-count", ["object_class"]
)
PREDICTION_LOG_DROPPED = Counter(
    "prediction_log_dropped_total",
    "Prediction records not stored: queue full or the store failed",
    ["reason"],
)
SHADOW_REQUESTS = Counter(
    "shadow_requests_total",
    "Shadow calls to a candidate version by outcome (compared, failed, dropped: pool busy)",
    ["model", "version", "outcome"],
)
SHADOW_AGREEMENT = Histogram(
    "shadow_class_agreement",
    "Overlap (Jaccard) of the classes the champion and the shadow candidate find at a 0.5 score",
    ["model", "version"],
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
CANARY_FALLBACKS = Counter(
    "canary_fallbacks_total",
    "Canary requests answered by the champion because the candidate version was unavailable",
    ["model", "version"],
)


def render(extra_collectors: Iterable[Collector] = ()) -> tuple[bytes, str]:
    """The metrics in the Prometheus text format, and their content type.

    extra_collectors compute their values at scrape time (e.g. drift); they're added to this
    scrape only, so building several apps (as tests do) never registers one twice.
    """
    extra = CollectorRegistry()
    for collector in extra_collectors:
        extra.register(collector)
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry) + generate_latest(extra), CONTENT_TYPE_LATEST
    return generate_latest(REGISTRY) + generate_latest(extra), CONTENT_TYPE_LATEST
