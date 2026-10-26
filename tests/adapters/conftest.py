import psycopg
import pytest
from pymongo import MongoClient

from counter.adapters.count_repo import CountInMemoryRepo, CountMongoDBRepo, CountPostgresRepo

MONGO_TEST_DB = "test_counter"


@pytest.fixture
def postgres_repo(postgres_dsn):
    repo = CountPostgresRepo(postgres_dsn)
    repo.ensure_schema()
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute("TRUNCATE object_counts")
    yield repo
    repo.close()


@pytest.fixture
def mongo_repo(mongo_address):
    MongoClient(*mongo_address).drop_database(MONGO_TEST_DB)
    return CountMongoDBRepo(*mongo_address, MONGO_TEST_DB)


@pytest.fixture(
    params=[
        "memory",
        pytest.param("postgres", marks=pytest.mark.integration),
        pytest.param("mongo", marks=pytest.mark.integration),
    ]
)
def repo(request):
    """Every ObjectCountRepo adapter, so they are held to the same contract."""
    if request.param == "memory":
        return CountInMemoryRepo()
    return request.getfixturevalue(f"{request.param}_repo")
