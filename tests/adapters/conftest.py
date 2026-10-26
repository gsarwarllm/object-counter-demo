import os

import psycopg
import pytest
from pymongo import MongoClient

from counter.adapters.count_repo import CountInMemoryRepo, CountMongoDBRepo, CountPostgresRepo

MONGO_TEST_DB = "test_counter"


@pytest.fixture(scope="session")
def postgres_dsn():
    """TEST_POSTGRES_DSN if set (any running server), otherwise a throwaway container."""
    if dsn := os.environ.get("TEST_POSTGRES_DSN"):
        yield dsn
        return
    from testcontainers.community.postgres import PostgresContainer

    container = _start_or_skip(lambda: PostgresContainer("postgres:16-alpine", driver=None))
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture(scope="session")
def mongo_address():
    """TEST_MONGO_HOST/TEST_MONGO_PORT if set, otherwise a throwaway container."""
    if host := os.environ.get("TEST_MONGO_HOST"):
        yield host, int(os.environ.get("TEST_MONGO_PORT", "27017"))
        return
    from testcontainers.core.container import DockerContainer

    container = _start_or_skip(lambda: DockerContainer("mongo:7.0").with_exposed_ports(27017))
    try:
        address = container.get_container_host_ip(), int(container.get_exposed_port(27017))
        MongoClient(*address, serverSelectionTimeoutMS=30_000).admin.command("ping")
        yield address
    finally:
        container.stop()


def _start_or_skip(make_container):
    try:
        return make_container().start()
    except Exception as error:  # no Docker daemon, image pull failure, ...
        pytest.skip(f"Docker unavailable: {error}")


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
