import logging
from concurrent.futures import ThreadPoolExecutor

import pytest
from pymongo import MongoClient

from counter.adapters.count_repo import CountMongoDBRepo
from counter.domain.errors import RepositoryUnavailableError
from counter.domain.models import ObjectCount
from tests.adapters.conftest import MONGO_TEST_DB


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


def test_not_ready_when_database_is_down(unreachable_repo):
    with pytest.raises(RepositoryUnavailableError):
        unreachable_repo.check_ready()


@pytest.mark.integration
def test_object_class_has_a_unique_index(mongo_repo, mongo_address):
    mongo_repo.read_values()

    indexes = MongoClient(*mongo_address)[MONGO_TEST_DB].counter.index_information()

    assert indexes["object_class_unique"]["unique"] is True
    assert indexes["object_class_unique"]["key"] == [("object_class", 1)]


@pytest.mark.integration
def test_concurrent_first_counts_of_a_class_make_one_document(mongo_repo, mongo_address):
    """Regression: without the unique index, racing upserts could insert duplicates."""
    with ThreadPoolExecutor(max_workers=10) as executor:
        list(
            executor.map(
                lambda _: mongo_repo.update_values([ObjectCount("cat", 1), ObjectCount("dog", 2)]),
                range(20),
            )
        )

    collection = MongoClient(*mongo_address)[MONGO_TEST_DB].counter
    assert collection.count_documents({"object_class": "cat"}) == 1
    assert sorted(mongo_repo.read_values(), key=lambda c: c.object_class) == [
        ObjectCount("cat", 20),
        ObjectCount("dog", 40),
    ]


@pytest.mark.integration
def test_existing_duplicates_are_reported_and_counting_keeps_working(mongo_address, caplog):
    client = MongoClient(*mongo_address)
    client.drop_database(MONGO_TEST_DB)
    client[MONGO_TEST_DB].counter.insert_many(
        [{"object_class": "cat", "count": 1}, {"object_class": "cat", "count": 2}]
    )
    repo = CountMongoDBRepo(*mongo_address, MONGO_TEST_DB)

    with caplog.at_level(logging.ERROR):
        repo.update_values([ObjectCount("dog", 1)])

    assert "duplicate object_class documents" in caplog.text
    assert ObjectCount("dog", 1) in repo.read_values()


def test_empty_update_needs_no_database(unreachable_repo):
    unreachable_repo.update_values([])  # nothing to write: no round trip, no error
