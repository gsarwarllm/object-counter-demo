import pytest

from counter import config
from counter.adapters.count_repo import CountInMemoryRepo, CountMongoDBRepo, CountPostgresRepo
from counter.adapters.debug_image_writer import FileDebugImageWriter
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


@pytest.mark.parametrize(
    ("env", "detector_type"), [("dev", FakeObjectDetector), ("prod", TFSObjectDetector)]
)
def test_env_selects_detector(monkeypatch, env, detector_type):
    monkeypatch.setenv("ENV", env)

    assert isinstance(config.get_object_detector(), detector_type)


def test_unknown_env_is_rejected(monkeypatch):
    monkeypatch.setenv("ENV", "staging")

    with pytest.raises(ValueError, match="Unknown ENV 'staging'"):
        config.get_object_detector()


def test_debug_images_are_off_by_default(monkeypatch):
    monkeypatch.delenv("DEBUG_IMAGES", raising=False)

    assert config.get_debug_image_writer() is None


def test_debug_images_flag_enables_the_writer(monkeypatch):
    monkeypatch.setenv("DEBUG_IMAGES", "1")

    assert isinstance(config.get_debug_image_writer(), FileDebugImageWriter)
