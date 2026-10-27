from datetime import timedelta

import pytest

from counter import config
from counter.adapters.count_repo import CountInMemoryRepo, CountMongoDBRepo, CountPostgresRepo
from counter.adapters.debug_image_writer import FileDebugImageWriter
from counter.adapters.model_manifest import write_lock
from counter.adapters.object_detector import FakeObjectDetector, TFSObjectDetector
from counter.adapters.prediction_log import BackgroundPredictionLog, InMemoryPredictionLog


def test_dev_defaults_to_memory_repo(monkeypatch):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.delenv("COUNT_REPO", raising=False)

    assert isinstance(config.get_count_repo(), CountInMemoryRepo)


def test_prod_defaults_to_mongo_repo(monkeypatch):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.delenv("COUNT_REPO", raising=False)

    assert isinstance(config.get_count_repo(), CountMongoDBRepo)


def test_count_repo_selects_postgres(monkeypatch):
    monkeypatch.setenv("COUNT_REPO", "postgres")
    monkeypatch.setenv("DATABASE_URL", "host=127.0.0.1 port=1 dbname=counter user=counter")

    repo = config.get_count_repo()
    try:
        assert isinstance(repo, CountPostgresRepo)
    finally:
        repo.close()


def test_unknown_count_repo_is_rejected(monkeypatch):
    monkeypatch.setenv("COUNT_REPO", "excel")

    with pytest.raises(ValueError, match="Unknown COUNT_REPO 'excel'"):
        config.get_count_repo()


def test_dev_serves_every_manifest_model_with_fakes(monkeypatch):
    monkeypatch.setenv("ENV", "dev")

    registry = config.get_detector_registry()

    assert registry.names == ["acme_shelf_detector", "ssd_mobilenet_v2"]
    assert registry.default_model == "ssd_mobilenet_v2"
    assert all(isinstance(model.detector, FakeObjectDetector) for model in registry.models)
    assert all(model.version is None for model in registry.models)


def test_prod_pins_the_pulled_versions(monkeypatch, tmp_path):
    lock = tmp_path / "models.lock.json"
    write_lock({"ssd_mobilenet_v2": "2", "acme_shelf_detector": "1"}, lock)
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("MODELS_LOCK", str(lock))

    model = config.get_detector_registry().get("ssd_mobilenet_v2")

    assert model.version == "2"
    assert isinstance(model.detector, TFSObjectDetector)
    assert model.detector.url.endswith("/v1/models/ssd_mobilenet_v2/versions/2:predict")


def test_prod_without_pulled_models_fails_fast(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("MODELS_LOCK", str(tmp_path / "missing.json"))

    with pytest.raises(ValueError, match="make pull-models"):
        config.get_detector_registry()


def test_unknown_env_is_rejected(monkeypatch):
    monkeypatch.setenv("ENV", "staging")

    with pytest.raises(ValueError, match="Unknown ENV 'staging'"):
        config.get_detector_registry()


def test_debug_images_are_off_by_default(monkeypatch):
    monkeypatch.delenv("DEBUG_IMAGES", raising=False)

    assert config.get_debug_image_writer() is None


def test_debug_images_flag_enables_the_writer(monkeypatch):
    monkeypatch.setenv("DEBUG_IMAGES", "1")

    assert isinstance(config.get_debug_image_writer(), FileDebugImageWriter)


@pytest.mark.parametrize(("env", "expected"), [("dev", "memory"), ("prod", "postgres")])
def test_prediction_log_defaults(monkeypatch, env, expected):
    monkeypatch.setenv("ENV", env)
    monkeypatch.delenv("PREDICTION_LOG", raising=False)
    # Don't open a real connection pool: only which store is built matters here.
    monkeypatch.setattr(config, "PostgresPredictionLog", lambda conninfo, timeout: "postgres")

    log = config.get_prediction_log()

    if expected == "memory":
        assert isinstance(log, InMemoryPredictionLog)
    else:
        assert isinstance(log, BackgroundPredictionLog)


def test_prediction_log_can_be_off(monkeypatch):
    monkeypatch.setenv("PREDICTION_LOG", "none")

    assert config.get_prediction_log() is None


def test_unknown_prediction_log_is_rejected(monkeypatch):
    monkeypatch.setenv("PREDICTION_LOG", "kafka")

    with pytest.raises(ValueError, match="Unknown PREDICTION_LOG 'kafka'"):
        config.get_prediction_log()


def test_drift_settings_come_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("BASELINES_DIR", str(tmp_path))
    monkeypatch.setenv("DRIFT_WINDOW_HOURS", "6")
    monkeypatch.setenv("DRIFT_MIN_IMAGES", "10")
    monkeypatch.setenv("DRIFT_CACHE_SECONDS", "0")

    assert config.get_drift_settings() == config.DriftSettings(
        tmp_path, timedelta(hours=6), 10, 0.0
    )


@pytest.mark.parametrize(("mode", "expected"), [("off", None), ("shadow", "3"), ("canary", "3")])
def test_prod_serves_the_candidate_only_in_a_release_mode(monkeypatch, tmp_path, mode, expected):
    lock = tmp_path / "models.lock.json"
    write_lock({"ssd_mobilenet_v2": "2", "acme_shelf_detector": "1"}, lock)
    write_lock({"ssd_mobilenet_v2": "3"}, tmp_path / "candidates.lock.json")
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("MODELS_LOCK", str(lock))
    monkeypatch.setenv("RELEASE_MODE", mode)

    registry = config.get_detector_registry()

    candidate = registry.get("ssd_mobilenet_v2").candidate
    assert (candidate.version if candidate else None) == expected
    assert registry.get("acme_shelf_detector").candidate is None
    if candidate:
        assert candidate.detector.url.endswith("/v1/models/ssd_mobilenet_v2/versions/3:predict")


def test_release_settings_default_to_off(monkeypatch):
    settings = config.get_release_settings()

    assert (settings.mode, settings.canary_percent) == ("off", 10.0)


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    [
        ("RELEASE_MODE", "blue-green", "Unknown RELEASE_MODE"),
        ("CANARY_PERCENT", "150", "between 0 and 100"),
    ],
)
def test_invalid_release_settings_are_rejected(monkeypatch, variable, value, message):
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=message):
        config.get_release_settings()
