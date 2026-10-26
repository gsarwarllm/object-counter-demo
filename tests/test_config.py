import pytest

from counter import config
from counter.adapters.count_repo import CountInMemoryRepo, CountMongoDBRepo, CountPostgresRepo


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
