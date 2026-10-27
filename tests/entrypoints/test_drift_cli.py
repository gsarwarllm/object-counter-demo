import json

import pytest

from counter import config
from counter.adapters.prediction_log import InMemoryPredictionLog
from counter.entrypoints import drift
from counter.monitoring.baseline import Baseline, save_baseline
from counter.monitoring.drift import distributions
from tests.monitoring.helpers import confident_cats, record, unsure_model


@pytest.fixture
def setup(monkeypatch, tmp_path):
    """Dev models (version "latest"), a baseline for the default model, and a prefilled log."""
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("BASELINES_DIR", str(tmp_path))
    monkeypatch.setenv("DRIFT_MIN_IMAGES", "5")
    save_baseline(
        Baseline("ssd_mobilenet_v2", "latest", "t", "test", distributions(confident_cats(50))),
        tmp_path,
    )
    log = InMemoryPredictionLog()
    monkeypatch.setattr(config, "get_prediction_log", lambda: log)

    def fill(records):
        for item in records:
            log.append(
                record(item.scores, item.classes, model="ssd_mobilenet_v2", version="latest")
            )

    return fill


def test_prints_a_report_per_version_with_a_baseline(setup, capsys):
    setup(confident_cats(10))

    assert drift.main([]) == 0

    output = json.loads(capsys.readouterr().out)
    (report,) = output["reports"]
    assert (report["model"], report["window_images"], report["drifted"]) == (
        "ssd_mobilenet_v2",
        10,
        False,
    )
    assert output["without_baseline"] == ["acme_shelf_detector@latest"]


def test_fail_on_drift_sets_the_exit_code(setup, capsys):
    setup(unsure_model(10))

    assert drift.main([]) == 0
    assert drift.main(["--fail-on-drift"]) == 1


def test_needs_a_prediction_log(monkeypatch):
    monkeypatch.setattr(config, "get_prediction_log", lambda: None)

    with pytest.raises(SystemExit, match="PREDICTION_LOG=none"):
        drift.main([])
