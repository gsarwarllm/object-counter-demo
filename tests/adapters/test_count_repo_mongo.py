import pytest

from counter.adapters.count_repo import CountMongoDBRepo
from counter.domain.errors import RepositoryUnavailableError
from counter.domain.models import ObjectCount


@pytest.fixture
def unreachable_repo():
    # Port 1 refuses connections, so this doesn't need a database.
    repo = CountMongoDBRepo("127.0.0.1", 1, "test_counter", timeout=0.2)
    yield repo
    repo.close()


def test_read_raises_domain_error_when_database_is_down(unreachable_repo):
    with pytest.raises(RepositoryUnavailableError):
        unreachable_repo.read_values()


def test_update_raises_domain_error_when_database_is_down(unreachable_repo):
    with pytest.raises(RepositoryUnavailableError):
        unreachable_repo.update_values([ObjectCount("cat", 1)])
