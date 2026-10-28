import logging
import queue
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from psycopg_pool import ConnectionPool

from counter.domain.models import ImageStats, PredictionRecord
from counter.domain.ports import PredictionLog
from counter.metrics import PREDICTION_LOG_DROPPED

logger = logging.getLogger(__name__)

# Applied in order on first use; each file is idempotent.
SCHEMA_FILES = [
    Path(__file__).parent / "sql" / "002_prediction_logs.sql",
    Path(__file__).parent / "sql" / "003_prediction_logs_image_stats.sql",
    Path(__file__).parent / "sql" / "005_prediction_logs_retention.sql",
]
# Arbitrary constant identifying this schema's advisory lock (see count_repo.py).
SCHEMA_LOCK_ID = 7_428_312
# Upper bound for one read, so a drift check on a busy model stays cheap.
MAX_READ_RECORDS = 50_000
# Retention deletes in batches, so one purge never holds many row locks or a long transaction.
PURGE_BATCH = 10_000
PURGE_INTERVAL_SECONDS = 3600.0


class InMemoryPredictionLog(PredictionLog):
    """Per-process and lost on restart: for dev and tests."""

    def __init__(self) -> None:
        self.__records: list[PredictionRecord] = []
        self.__lock = threading.Lock()

    def append(self, record: PredictionRecord) -> None:
        with self.__lock:
            self.__records.append(record)

    def read(self, model: str, version: str, since: datetime) -> list[PredictionRecord]:
        with self.__lock:
            return [
                record
                for record in self.__records
                if record.model == model and record.version == version and record.logged_at >= since
            ][-MAX_READ_RECORDS:]


class PostgresPredictionLog(PredictionLog):
    """The table prediction_logs (schema in sql/002_*.sql, 003_*.sql and 005_*.sql).

    With a retention period, rows older than it are deleted at most every purge_interval
    seconds, from append() (which runs in the background writer, so requests never wait).
    """

    INSERT = (
        "INSERT INTO prediction_logs (logged_at, model, version, scores, classes, "
        "width, height, color_mode, brightness, contrast) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    SELECT = (
        "SELECT model, version, logged_at, scores, classes, "
        "width, height, color_mode, brightness, contrast FROM prediction_logs "
        "WHERE model = %s AND version = %s AND logged_at >= %s "
        "ORDER BY logged_at DESC LIMIT %s"
    )
    PURGE = (
        "DELETE FROM prediction_logs WHERE id IN "
        "(SELECT id FROM prediction_logs WHERE logged_at < %s LIMIT %s)"
    )

    def __init__(
        self,
        conninfo: str,
        timeout: float = 5.0,
        retention: timedelta | None = None,
        purge_interval: float = PURGE_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # A small pool of its own: writes come from one background thread per process.
        self.__pool = ConnectionPool(
            conninfo,
            min_size=1,
            max_size=2,
            timeout=timeout,
            kwargs={"connect_timeout": max(1, int(timeout))},
            open=True,
        )
        self.__schema_ready = False
        self.__retention = retention
        self.__purge_interval = purge_interval
        self.__clock = clock
        self.__purged_at: float | None = None

    def append(self, record: PredictionRecord) -> None:
        self.__ensure_schema()
        self.__purge_if_due()
        stats = record.image
        with self.__pool.connection() as conn:
            conn.execute(
                self.INSERT,
                (
                    record.logged_at,
                    record.model,
                    record.version,
                    record.scores,
                    record.classes,
                    *(
                        (
                            stats.width,
                            stats.height,
                            stats.color_mode,
                            stats.brightness,
                            stats.contrast,
                        )
                        if stats
                        else (None,) * 5
                    ),
                ),
            )

    def read(self, model: str, version: str, since: datetime) -> list[PredictionRecord]:
        self.__ensure_schema()
        with self.__pool.connection() as conn:
            rows = conn.execute(self.SELECT, (model, version, since, MAX_READ_RECORDS)).fetchall()
        records = [
            PredictionRecord(
                model,
                version,
                logged_at,
                list(scores),
                list(classes),
                ImageStats(width, height, color_mode, brightness, contrast)
                if width is not None
                else None,
            )
            for (
                model,
                version,
                logged_at,
                scores,
                classes,
                width,
                height,
                color_mode,
                brightness,
                contrast,
            ) in rows
        ]
        return records[::-1]

    def purge(self, older_than: datetime) -> int:
        """Deletes rows logged before older_than; returns how many."""
        self.__ensure_schema()
        deleted = 0
        while True:
            with self.__pool.connection() as conn:
                batch = conn.execute(self.PURGE, (older_than, PURGE_BATCH)).rowcount
            deleted += batch
            if batch < PURGE_BATCH:
                return deleted

    def close(self) -> None:
        self.__pool.close()

    def __purge_if_due(self) -> None:
        if self.__retention is None:
            return
        now = self.__clock()
        if self.__purged_at is not None and now - self.__purged_at < self.__purge_interval:
            return
        self.__purged_at = now
        deleted = self.purge(datetime.now(UTC) - self.__retention)
        if deleted:
            logger.info("Prediction log retention: deleted %d rows", deleted)

    def __ensure_schema(self) -> None:
        if self.__schema_ready:
            return
        with self.__pool.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_ID,))
            for schema_file in SCHEMA_FILES:
                conn.execute(schema_file.read_text())
        self.__schema_ready = True


class BackgroundPredictionLog(PredictionLog):
    """Writes through a queue and one background thread, so logging never slows a request or
    fails it. When the queue is full or the store fails, records are dropped and counted
    (prediction_log_dropped_total); monitoring data is allowed to have gaps, requests aren't.
    """

    def __init__(self, store: PredictionLog, max_queue: int = 1000) -> None:
        self.__store = store
        self.__queue: queue.Queue[PredictionRecord] = queue.Queue(maxsize=max_queue)
        self.__thread: threading.Thread | None = None
        self.__start_lock = threading.Lock()

    def append(self, record: PredictionRecord) -> None:
        self.__start()
        try:
            self.__queue.put_nowait(record)
        except queue.Full:
            PREDICTION_LOG_DROPPED.labels("queue_full").inc()

    def read(self, model: str, version: str, since: datetime) -> list[PredictionRecord]:
        return self.__store.read(model, version, since)

    def flush(self, timeout: float = 5.0) -> bool:
        """Waits until every queued record was handled; True if it finished in time."""
        done = threading.Event()

        def wait_for_queue() -> None:
            self.__queue.join()
            done.set()

        threading.Thread(target=wait_for_queue, daemon=True).start()
        return done.wait(timeout)

    def __start(self) -> None:
        # Started on first use, inside the worker process (threads don't survive a fork).
        with self.__start_lock:
            if self.__thread is None:
                self.__thread = threading.Thread(
                    target=self.__write_forever, name="prediction-log", daemon=True
                )
                self.__thread.start()

    def __write_forever(self) -> None:
        while True:
            record = self.__queue.get()
            try:
                self.__store.append(record)
            except Exception as error:  # the store may be down; the app must keep serving
                PREDICTION_LOG_DROPPED.labels("store_error").inc()
                logger.warning("Prediction log write failed: %s", error)
            finally:
                self.__queue.task_done()
