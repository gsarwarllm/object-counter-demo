import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout
from pymongo import ASCENDING, MongoClient, UpdateOne
from pymongo.errors import OperationFailure, PyMongoError

from counter.domain.errors import RepositoryUnavailableError
from counter.domain.models import ObjectCount
from counter.domain.ports import ObjectCountRepo

logger = logging.getLogger(__name__)

# Applied in order on first use; each file is idempotent.
SCHEMA_FILES = [
    Path(__file__).parent / "sql" / "001_object_counts.sql",
    Path(__file__).parent / "sql" / "004_object_counts_fillfactor.sql",
]
# MongoDB's error code for a duplicate key (here: when building the unique index).
MONGO_DUPLICATE_KEY = 11000
# Arbitrary constant identifying the schema-creation advisory lock.
SCHEMA_LOCK_ID = 7_428_311


class CountInMemoryRepo(ObjectCountRepo):
    def __init__(self) -> None:
        self.store: dict[str, ObjectCount] = {}

    def read_values(self, object_classes: list[str] | None = None) -> list[ObjectCount]:
        if object_classes is None:
            return list(self.store.values())

        return [
            self.store[object_class]
            for object_class in object_classes
            if object_class in self.store
        ]

    def update_values(self, new_values: list[ObjectCount]) -> None:
        for new_object_count in new_values:
            key = new_object_count.object_class
            try:
                stored_object_count = self.store[key]
                self.store[key] = ObjectCount(
                    key, stored_object_count.count + new_object_count.count
                )
            except KeyError:
                self.store[key] = ObjectCount(key, new_object_count.count)


class CountMongoDBRepo(ObjectCountRepo):
    def __init__(self, host: str, port: int, database: str, timeout: float = 5.0) -> None:
        # One client (and connection pool) for the repo's lifetime; it connects lazily.
        self.__client: MongoClient[dict[str, Any]] = MongoClient(
            host, port, serverSelectionTimeoutMS=int(timeout * 1000)
        )
        self.__counter_col = self.__client[database].counter
        self.__index_ready = False

    def read_values(self, object_classes: list[str] | None = None) -> list[ObjectCount]:
        query = {"object_class": {"$in": object_classes}} if object_classes is not None else None
        with _mongo_errors():
            self.__ensure_index()
            counters = list(self.__counter_col.find(query))
        return [ObjectCount(counter["object_class"], counter["count"]) for counter in counters]

    def update_values(self, new_values: list[ObjectCount]) -> None:
        if not new_values:
            return
        # One round trip for all classes of a request.
        operations = [
            UpdateOne(
                {"object_class": value.object_class},
                {"$inc": {"count": value.count}},
                upsert=True,
            )
            for value in new_values
        ]
        with _mongo_errors():
            self.__ensure_index()
            self.__counter_col.bulk_write(operations, ordered=False)

    def __ensure_index(self) -> None:
        """A unique index on object_class: lookups by class use it, and two concurrent upserts
        of a new class can't insert two documents (MongoDB retries the losing upsert)."""
        if self.__index_ready:
            return
        try:
            self.__counter_col.create_index(
                [("object_class", ASCENDING)], unique=True, name="object_class_unique"
            )
        except OperationFailure as error:
            if error.code != MONGO_DUPLICATE_KEY:
                raise
            # Data written before the index can hold duplicates; counting keeps working, but
            # they must be merged by hand before the index can be built.
            logger.error(
                "MongoDB collection %s has duplicate object_class documents; merge them to "
                "build the unique index: %s",
                self.__counter_col.full_name,
                error,
            )
        self.__index_ready = True

    def check_ready(self) -> None:
        with _mongo_errors():
            self.__client.admin.command("ping")

    def close(self) -> None:
        self.__client.close()


@contextmanager
def _mongo_errors() -> Iterator[None]:
    try:
        yield
    except PyMongoError as error:
        raise RepositoryUnavailableError(f"MongoDB unavailable: {error}") from error


class CountPostgresRepo(ObjectCountRepo):
    """Counts in the PostgreSQL table object_counts (schema in sql/001_object_counts.sql)."""

    UPSERT = """
        INSERT INTO object_counts (object_class, count) VALUES (%s, %s)
        ON CONFLICT (object_class)
        DO UPDATE SET count = object_counts.count + EXCLUDED.count, updated_at = now()
    """
    SELECT_ALL = "SELECT object_class, count FROM object_counts ORDER BY object_class"
    SELECT_CLASSES = (
        "SELECT object_class, count FROM object_counts "
        "WHERE object_class = ANY(%s) ORDER BY object_class"
    )

    def __init__(self, conninfo: str, timeout: float = 5.0, max_size: int = 10) -> None:
        # Opens in the background, so the app starts even while the database is down.
        self.__pool = ConnectionPool(
            conninfo,
            min_size=1,
            max_size=max_size,
            timeout=timeout,
            kwargs={"connect_timeout": max(1, int(timeout))},
            open=True,
        )
        self.__schema_ready = False

    def read_values(self, object_classes: list[str] | None = None) -> list[ObjectCount]:
        params: tuple[Any, ...]
        if object_classes is None:
            query, params = self.SELECT_ALL, ()
        else:
            query, params = self.SELECT_CLASSES, (object_classes,)
        with self.__connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [ObjectCount(object_class, count) for object_class, count in rows]

    def update_values(self, new_values: list[ObjectCount]) -> None:
        # One transaction; a fixed row order avoids deadlocks between concurrent requests.
        rows = sorted((value.object_class, value.count) for value in new_values)
        with self.__connection() as conn, conn.cursor() as cursor:
            cursor.executemany(self.UPSERT, rows)

    def check_ready(self) -> None:
        # Also creates the schema on first use, like any other query.
        with self.__connection() as conn:
            conn.execute("SELECT 1")

    def close(self) -> None:
        self.__pool.close()

    def ensure_schema(self) -> None:
        # Concurrent CREATE TABLE IF NOT EXISTS can still fail with a unique violation on
        # pg_type; the advisory lock (released at commit) serializes it across processes.
        with self.__pool.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_ID,))
            for schema_file in SCHEMA_FILES:
                conn.execute(schema_file.read_text())
        self.__schema_ready = True

    @contextmanager
    def __connection(self) -> Iterator[psycopg.Connection[Any]]:
        try:
            if not self.__schema_ready:
                self.ensure_schema()
            with self.__pool.connection() as conn:
                yield conn
        except (psycopg.OperationalError, PoolTimeout) as error:
            raise RepositoryUnavailableError(f"PostgreSQL unavailable: {error}") from error
