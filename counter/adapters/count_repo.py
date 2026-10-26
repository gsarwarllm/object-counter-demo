from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout
from pymongo import MongoClient

from counter.domain.errors import RepositoryUnavailableError
from counter.domain.models import ObjectCount
from counter.domain.ports import ObjectCountRepo

SCHEMA_FILE = Path(__file__).parent / "sql" / "001_object_counts.sql"


class CountInMemoryRepo(ObjectCountRepo):
    def __init__(self):
        self.store = {}

    def read_values(self, object_classes: list[str] | None = None) -> list[ObjectCount]:
        if object_classes is None:
            return list(self.store.values())

        return [
            self.store[object_class]
            for object_class in object_classes
            if object_class in self.store
        ]

    def update_values(self, new_values: list[ObjectCount]):
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
    def __init__(self, host, port, database):
        self.__host = host
        self.__port = port
        self.__database = database

    def __get_counter_col(self):
        client = MongoClient(self.__host, self.__port)
        db = client[self.__database]
        counter_col = db.counter
        return counter_col

    def read_values(self, object_classes: list[str] | None = None) -> list[ObjectCount]:
        counter_col = self.__get_counter_col()
        query = {"object_class": {"$in": object_classes}} if object_classes is not None else None
        counters = counter_col.find(query)
        object_counts = []
        for counter in counters:
            object_counts.append(ObjectCount(counter["object_class"], counter["count"]))
        return object_counts

    def update_values(self, new_values: list[ObjectCount]):
        counter_col = self.__get_counter_col()
        for value in new_values:
            counter_col.update_one(
                {"object_class": value.object_class}, {"$inc": {"count": value.count}}, upsert=True
            )


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

    def __init__(self, conninfo: str, timeout: float = 5.0, max_size: int = 10):
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
        if object_classes is None:
            query, params = self.SELECT_ALL, ()
        else:
            query, params = self.SELECT_CLASSES, (object_classes,)
        with self.__connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [ObjectCount(object_class, count) for object_class, count in rows]

    def update_values(self, new_values: list[ObjectCount]):
        # One transaction; a fixed row order avoids deadlocks between concurrent requests.
        rows = sorted((value.object_class, value.count) for value in new_values)
        with self.__connection() as conn, conn.cursor() as cursor:
            cursor.executemany(self.UPSERT, rows)

    def close(self):
        self.__pool.close()

    def ensure_schema(self):
        with self.__pool.connection() as conn:
            conn.execute(SCHEMA_FILE.read_text())
        self.__schema_ready = True

    @contextmanager
    def __connection(self):
        try:
            if not self.__schema_ready:
                self.ensure_schema()
            with self.__pool.connection() as conn:
                yield conn
        except (psycopg.OperationalError, PoolTimeout) as error:
            raise RepositoryUnavailableError(f"PostgreSQL unavailable: {error}") from error
