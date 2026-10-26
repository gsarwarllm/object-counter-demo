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
