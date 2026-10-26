from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from counter.adapters.count_repo import CountPostgresRepo
from counter.domain.errors import RepositoryUnavailableError
from counter.domain.models import ObjectCount

# Port 1 refuses connections immediately, so these tests don't need a database.
UNREACHABLE_DSN = "host=127.0.0.1 port=1 dbname=counter user=counter connect_timeout=1"


@pytest.fixture
def unreachable_repo():
    repo = CountPostgresRepo(UNREACHABLE_DSN, timeout=0.5)
    yield repo
    repo.close()


def test_read_raises_domain_error_when_database_is_down(unreachable_repo):
    with pytest.raises(RepositoryUnavailableError):
        unreachable_repo.read_values()


def test_update_raises_domain_error_when_database_is_down(unreachable_repo):
    with pytest.raises(RepositoryUnavailableError):
        unreachable_repo.update_values([ObjectCount("cat", 1)])


@pytest.mark.integration
def test_counts_persist_across_repo_instances(postgres_repo, postgres_dsn):
    postgres_repo.update_values([ObjectCount("cat", 2)])

    other_repo = CountPostgresRepo(postgres_dsn)
    try:
        assert other_repo.read_values() == [ObjectCount("cat", 2)]
    finally:
        other_repo.close()


@pytest.mark.integration
def test_concurrent_first_use_creates_the_schema_once(postgres_dsn):
    """Regression: concurrent CREATE TABLE IF NOT EXISTS used to fail with a unique violation."""
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute("DROP TABLE IF EXISTS object_counts")
    repo = CountPostgresRepo(postgres_dsn)
    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(lambda _: repo.update_values([ObjectCount("cat", 1)]), range(10)))

        assert repo.read_values() == [ObjectCount("cat", 10)]
    finally:
        repo.close()
