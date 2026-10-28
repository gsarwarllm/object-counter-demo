import json
import threading
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from werkzeug.serving import make_server

from counter.adapters.detector_registry import DetectorRegistry, ServedModel
from counter.adapters.model_manifest import candidates_lock, load_manifest, write_lock
from counter.adapters.object_detector import FakeObjectDetector
from counter.adapters.prediction_log import InMemoryPredictionLog
from counter.entrypoints import drift as drift_cli
from counter.entrypoints.webapp import create_app
from counter.monitoring.baseline import load_baseline
from counter.monitoring.drift import FEATURES, compare, distributions
from counter.monitoring.monitor import DriftMonitor
from scripts import demo_data

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
DAY_AGO = NOW - timedelta(hours=24)
MODERATE = {"brightness", "classes"}


def statuses(profile):
    reference = demo_data.generate(
        demo_data.HEALTHY, "m", "1", 1000, demo_data.BASELINE_SEED, DAY_AGO, NOW
    )
    window = demo_data.generate(profile, "m", "1", 500, demo_data.WINDOW_SEED, DAY_AGO, NOW)
    report = compare("m", "1", distributions(reference), distributions(window), min_images=30)
    return {feature.feature: feature.status for feature in report.features}


def test_night_camera_drifts_on_every_feature():
    assert statuses(demo_data.NIGHT_CAMERA) == dict.fromkeys(FEATURES, "drift")


def test_darker_shelves_drift_moderately_in_brightness_and_classes_only():
    expected = {feature: "moderate" if feature in MODERATE else "stable" for feature in FEATURES}

    assert statuses(demo_data.SLIGHTLY_DARKER_SHELVES) == expected


def test_healthy_traffic_is_stable_against_its_baseline():
    assert statuses(demo_data.HEALTHY) == dict.fromkeys(FEATURES, "stable")


def test_generate_is_repeatable_and_spread_over_the_period():
    first = demo_data.generate(demo_data.HEALTHY, "m", "1", 50, 7, DAY_AGO, NOW)
    second = demo_data.generate(demo_data.HEALTHY, "m", "1", 50, 7, DAY_AGO, NOW)

    assert first == second
    assert first[0].logged_at == DAY_AGO
    assert all(DAY_AGO <= record.logged_at < NOW for record in first)
    assert all(len(r.scores) == len(r.classes) == demo_data.SCORES_PER_IMAGE for r in first)


def write_manifest(tmp_path):
    (tmp_path / "labels.json").write_text('[{"id": 1, "display_name": "person"}]')
    models = [
        {"name": name, "serving": "fake", "label_map": "labels.json"}
        for name in ("ssd_mobilenet_v2", "acme_shelf_detector")
    ]
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"default_model": "ssd_mobilenet_v2", "models": models}))
    return path


def test_served_versions_are_the_pulled_champions_and_candidates(tmp_path):
    manifest = load_manifest(write_manifest(tmp_path))
    lock = tmp_path / "models.lock.json"
    write_lock({"ssd_mobilenet_v2": "1", "acme_shelf_detector": "1"}, lock)
    write_lock({"acme_shelf_detector": "2"}, candidates_lock(lock))

    versions = demo_data.served_versions(manifest, lock)

    assert versions == [
        demo_data.ServedVersion("ssd_mobilenet_v2", "1", "champion"),
        demo_data.ServedVersion("acme_shelf_detector", "1", "champion"),
        demo_data.ServedVersion("acme_shelf_detector", "2", "candidate"),
    ]
    assert [demo_data.scenario(v) for v in versions] == [
        demo_data.NIGHT_CAMERA,
        demo_data.SLIGHTLY_DARKER_SHELVES,
        demo_data.HEALTHY,
    ]


def test_served_versions_are_latest_when_nothing_is_pulled(tmp_path):
    manifest = load_manifest(write_manifest(tmp_path))

    versions = demo_data.served_versions(manifest, tmp_path / "missing.lock.json")

    assert [(v.model, v.version) for v in versions] == [
        ("ssd_mobilenet_v2", "latest"),
        ("acme_shelf_detector", "latest"),
    ]


def test_seed_writes_baselines_and_the_monitor_reports_each_scenario(tmp_path):
    log = InMemoryPredictionLog()
    versions = [
        demo_data.ServedVersion("ssd_mobilenet_v2", "1", "champion"),
        demo_data.ServedVersion("acme_shelf_detector", "1", "champion"),
        demo_data.ServedVersion("acme_shelf_detector", "2", "candidate"),
    ]

    lines = demo_data.seed(log, versions, tmp_path, timedelta(hours=24))
    monitor = DriftMonitor(log, [(v.model, v.version) for v in versions], tmp_path, cache_seconds=0)
    reports = {(r.model, r.version): r for r in monitor.reports()}

    assert len(lines) == 3 and "night camera" in lines[0]
    assert load_baseline(tmp_path, "acme_shelf_detector", "2").distributions.images == 1000
    assert all(r.window_images == demo_data.WINDOW_IMAGES for r in reports.values())
    assert {f.status for f in reports["ssd_mobilenet_v2", "1"].features} == {"drift"}
    assert {
        f.feature for f in reports["acme_shelf_detector", "1"].features if f.status != "stable"
    } == MODERATE
    assert {f.status for f in reports["acme_shelf_detector", "2"].features} == {"stable"}


def test_refuses_to_run_without_demo(capsys, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")

    assert demo_data.main([]) == 2
    assert "--demo" in capsys.readouterr().err


@pytest.fixture
def app_url():
    detectors = DetectorRegistry(
        [ServedModel(name, None, FakeObjectDetector()) for name in ("a", "b")], "a"
    )
    server = make_server("127.0.0.1", 0, create_app(detectors=detectors))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_send_requests_mixes_valid_and_invalid_requests(app_url):
    statuses = demo_data.send_requests(app_url, 30)

    assert statuses == {200: 27, 400: 3}


@pytest.mark.integration
def test_main_seeds_postgres_and_make_drift_reports_it(postgres_dsn, tmp_path, monkeypatch, capsys):
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute("DROP TABLE IF EXISTS prediction_logs")
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", postgres_dsn)
    monkeypatch.setenv("PREDICTION_LOG", "postgres")
    monkeypatch.setenv("BASELINES_DIR", str(tmp_path / "baselines"))
    monkeypatch.setenv("MODELS_LOCK", str(tmp_path / "missing.lock.json"))
    args = ["--demo", "--lock", str(tmp_path / "missing.lock.json")]

    assert demo_data.main(args) == 0
    assert demo_data.main([*args, "--reset"]) == 0  # the second run replaces the first one's rows
    capsys.readouterr()
    assert drift_cli.main([]) == 0
    reports = {r["model"]: r for r in json.loads(capsys.readouterr().out)["reports"]}

    with psycopg.connect(postgres_dsn) as conn:
        (rows,) = conn.execute("SELECT count(*) FROM prediction_logs").fetchone()
    assert rows == 2 * demo_data.WINDOW_IMAGES
    assert reports["ssd_mobilenet_v2"]["drifted"]
    moderate = {
        f["feature"]
        for f in reports["acme_shelf_detector"]["features"]
        if f["status"] == "moderate"
    }
    assert moderate == MODERATE


def test_unreachable_app_is_reported_without_a_traceback(monkeypatch, capsys):
    monkeypatch.setattr(demo_data, "PostgresPredictionLog", lambda *args, **kwargs: FakeLog())
    monkeypatch.setattr(demo_data, "seed", lambda *args: [])

    assert demo_data.main(["--demo", "--requests", "1", "--url", "http://127.0.0.1:1"]) == 1
    assert "isn't reachable at http://127.0.0.1:1" in capsys.readouterr().err


class FakeLog:
    def close(self):
        pass
