import pytest

from counter import config
from counter.adapters.count_repo import CountInMemoryRepo, CountMongoDBRepo, CountPostgresRepo
from counter.adapters.debug_image_writer import FileDebugImageWriter
from counter.adapters.model_manifest import write_lock
from counter.adapters.object_detector import FakeObjectDetector, TFSObjectDetector


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
