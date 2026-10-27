"""Drift report for every served model version, as JSON on stdout.

    python -m counter.entrypoints.drift [--fail-on-drift]

Reads the prediction log (PREDICTION_LOG, usually postgres) and the baselines in BASELINES_DIR.
With --fail-on-drift the exit code is 1 when any feature's PSI reaches 0.25, for cron jobs or a
scheduled CI check.
"""

import argparse
import json
import sys
from dataclasses import asdict

from counter import config
from counter.logging_config import configure_logging
from counter.monitoring.drift import DriftReport
from counter.monitoring.monitor import DriftMonitor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prediction drift report per model version")
    parser.add_argument("--fail-on-drift", action="store_true", help="exit 1 if drift is found")
    args = parser.parse_args(argv)
    configure_logging()
    prediction_log = config.get_prediction_log()
    if prediction_log is None:
        sys.exit("PREDICTION_LOG=none: nothing to compare")
    settings = config.get_drift_settings()
    models = [
        (model.name, model.version or "latest") for model in config.get_detector_registry().models
    ]
    monitor = DriftMonitor(
        prediction_log,
        models,
        settings.baselines_dir,
        window=settings.window,
        min_images=settings.min_images,
        cache_seconds=0,
    )
    reports = monitor.reports()
    checked = {(report.model, report.version) for report in reports}
    output = {
        "reports": [_as_dict(report) for report in reports],
        "without_baseline": [
            f"{name}@{version}" for name, version in models if (name, version) not in checked
        ],
    }
    print(json.dumps(output, indent=2))
    return 1 if args.fail_on_drift and any(report.drifted for report in reports) else 0


def _as_dict(report: DriftReport) -> dict:
    return {**asdict(report), "drifted": report.drifted}


if __name__ == "__main__":
    sys.exit(main())
