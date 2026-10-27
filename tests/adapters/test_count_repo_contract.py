from concurrent.futures import ThreadPoolExecutor

import pytest

from counter.adapters.count_repo import CountInMemoryRepo
from counter.domain.models import ObjectCount


def by_class(object_counts):
    return sorted(object_counts, key=lambda object_count: object_count.object_class)


def test_empty_store_returns_nothing(repo):
    assert repo.read_values() == []


def test_updates_accumulate(repo):
    repo.update_values([ObjectCount("cat", 2)])
    repo.update_values([ObjectCount("cat", 2)])

    assert repo.read_values() == [ObjectCount("cat", 4)]


def test_read_all_returns_every_class(repo):
    repo.update_values([ObjectCount("cat", 1), ObjectCount("dog", 3)])

    assert by_class(repo.read_values()) == [ObjectCount("cat", 1), ObjectCount("dog", 3)]


def test_read_selected_classes_only(repo):
    repo.update_values([ObjectCount("cat", 1), ObjectCount("dog", 3), ObjectCount("cup", 2)])

    assert by_class(repo.read_values(["cat", "cup"])) == [
        ObjectCount("cat", 1),
        ObjectCount("cup", 2),
    ]


def test_unknown_classes_are_not_returned(repo):
    repo.update_values([ObjectCount("cat", 1)])

    assert repo.read_values(["cat", "unicorn"]) == [ObjectCount("cat", 1)]
    assert repo.read_values(["unicorn"]) == []
    assert repo.read_values([]) == []


def test_reachable_store_is_ready(repo):
    repo.check_ready()


def test_concurrent_updates_are_not_lost(repo):
    if isinstance(repo, CountInMemoryRepo):
        pytest.skip("the in-memory repo is per-process and not meant for concurrent writers")

    with ThreadPoolExecutor(max_workers=20) as executor:
        for _ in range(20):
            executor.submit(repo.update_values, [ObjectCount("cat", 1)])

    assert repo.read_values(["cat"]) == [ObjectCount("cat", 20)]
