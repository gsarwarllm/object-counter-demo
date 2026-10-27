import logging
import threading
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from prometheus_client import REGISTRY

from counter.adapters.prediction_log import (
    SCHEMA_FILES,
    BackgroundPredictionLog,
    InMemoryPredictionLog,
    PostgresPredictionLog,
)
from tests.monitoring.helpers import photo, record

UNREACHABLE_DSN = "host=127.0.0.1 port=1 dbname=counter user=counter connect_timeout=1"
HOUR_AGO = datetime.now(UTC) - timedelta(hours=1)


def dropped(reason):
    return REGISTRY.get_sample_value("prediction_log_dropped_total", {"reason": reason}) or 0.0


def test_in_memory_reads_one_version_since_a_time():
    log = InMemoryPredictionLog()
    log.append(record([0.1], logged_at=HOUR_AGO - timedelta(hours=1)))
    log.append(record([0.2], version="2"))
    log.append(record([0.3], model="other"))
    log.append(record([0.4]))
    log.append(record([0.5]))

    assert [r.scores for r in log.read("m", "1", HOUR_AGO)] == [[0.4], [0.5]]


class TestBackground:
    def test_writes_in_a_background_thread(self):
        store = InMemoryPredictionLog()
        log = BackgroundPredictionLog(store)

        log.append(record([0.9]))

        assert log.flush()
        assert [r.scores for r in log.read("m", "1", HOUR_AGO)] == [[0.9]]

    def test_drops_records_when_the_queue_is_full(self):
        release = threading.Event()

        class SlowStore(InMemoryPredictionLog):
            def append(self, item):
                release.wait(5)
                super().append(item)

        log = BackgroundPredictionLog(SlowStore(), max_queue=1)
        before = dropped("queue_full")

        for _ in range(4):  # one being written, one queued, the rest dropped
            log.append(record([0.9]))
        release.set()

        assert log.flush()
        assert dropped("queue_full") >= before + 1

    def test_store_failures_are_counted_and_never_raised(self, caplog):
        class DownStore(InMemoryPredictionLog):
            def append(self, item):
                raise OSError("connection refused")

        log = BackgroundPredictionLog(DownStore())
        before = dropped("store_error")

        with caplog.at_level(logging.WARNING):
            log.append(record([0.9]))
            assert log.flush()

        assert dropped("store_error") == before + 1
        assert "Prediction log write failed: connection refused" in caplog.messages


def test_postgres_errors_reach_the_caller_directly():
    log = PostgresPredictionLog(UNREACHABLE_DSN, timeout=0.5)
    try:
        with pytest.raises(psycopg.OperationalError):
            log.append(record([0.9]))
    finally:
        log.close()


@pytest.fixture
def postgres_log(postgres_dsn):
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute("DROP TABLE IF EXISTS prediction_logs")
    log = PostgresPredictionLog(postgres_dsn)
    yield log
    log.close()


@pytest.mark.integration
def test_postgres_round_trip(postgres_log):
    postgres_log.append(record([0.5], logged_at=HOUR_AGO - timedelta(hours=1)))
    postgres_log.append(
        record(
            [0.9, 0.25],
            ["cat", "dog"],
            logged_at=HOUR_AGO + timedelta(minutes=1),
            image=photo(800, 600, "RGBA", 120.5, 40.25),
        )
    )
    postgres_log.append(record([0.7], ["cup"], logged_at=HOUR_AGO + timedelta(minutes=2)))
    postgres_log.append(record([0.8], version="2"))

    records = postgres_log.read("m", "1", HOUR_AGO)

    assert [(r.scores, r.classes) for r in records] == [
        ([0.9, 0.25], ["cat", "dog"]),
        ([0.7], ["cup"]),
    ]
    assert records[0].logged_at == HOUR_AGO + timedelta(minutes=1)
    assert records[0].image == photo(800, 600, "RGBA", 120.5, 40.25)
    assert records[1].image is None


@pytest.mark.integration
def test_postgres_adds_the_image_columns_to_an_older_table(postgres_dsn):
    """A table created before X4 (002 only) gets the image columns on first use."""
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute("DROP TABLE IF EXISTS prediction_logs")
        conn.execute(SCHEMA_FILES[0].read_text())
        conn.execute(
            "INSERT INTO prediction_logs (model, version, scores, classes) "
            "VALUES ('m', '1', '{0.5}', '{cat}')"
        )
    log = PostgresPredictionLog(postgres_dsn)
    try:
        log.append(record([0.9], image=photo()))

        old, new = log.read("m", "1", HOUR_AGO)
    finally:
        log.close()

    assert (old.image, new.image) == (None, photo())
