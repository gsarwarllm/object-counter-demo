"""The API against real PostgreSQL and MongoDB (testcontainers, or TEST_* servers).

The detector is the dev fake (always one cat, score 0.9992), so these tests are about the
HTTP layer and the count store working together: persistence across app restarts, reads
that don't write, and concurrent requests.
"""

import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest
from pymongo import MongoClient

from counter.entrypoints.webapp import create_app

pytestmark = pytest.mark.integration

IMAGE = Path(__file__).parents[2] / "resources" / "images" / "cat.jpg"
MONGO_DB = "api_integration"


@pytest.fixture(params=["postgres", "mongo"])
def store(request, monkeypatch):
    """Configures COUNT_REPO for a clean real database; returns a function reading its totals."""
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("COUNT_REPO", request.param)
    if request.param == "postgres":
        dsn = request.getfixturevalue("postgres_dsn")
        monkeypatch.setenv("DATABASE_URL", dsn)
        with psycopg.connect(dsn) as conn:
            conn.execute("DROP TABLE IF EXISTS object_counts")

        def totals():
            with psycopg.connect(dsn) as conn:
                if conn.execute("SELECT to_regclass('object_counts')").fetchone()[0] is None:
                    return {}  # the table is created on the first write
                return dict(
                    conn.execute("SELECT object_class, count FROM object_counts").fetchall()
                )

    else:
        host, port = request.getfixturevalue("mongo_address")
        monkeypatch.setenv("MONGO_HOST", host)
        monkeypatch.setenv("MONGO_PORT", str(port))
        monkeypatch.setenv("MONGO_DB", MONGO_DB)
        MongoClient(host, port).drop_database(MONGO_DB)

        def totals():
            documents = MongoClient(host, port)[MONGO_DB].counter.find()
            return {document["object_class"]: document["count"] for document in documents}

    return totals


def count(client, threshold="0.5"):
    data = {"threshold": threshold, "file": (io.BytesIO(IMAGE.read_bytes()), "cat.jpg")}
    return client.post("/object-count", data=data, content_type="multipart/form-data")


def test_counts_are_stored_in_the_database(store):
    with create_app().test_client() as client:
        count(client)
        body = count(client).get_json()

    assert body["total_objects"] == [{"object_class": "cat", "count": 2}]
    assert store() == {"cat": 2}


def test_totals_survive_an_app_restart(store):
    with create_app().test_client() as client:
        count(client)

    with create_app().test_client() as restarted:
        # threshold 1.0 counts nothing new (the fake's score is below 1), so this only reads
        body = count(restarted, threshold="1.0").get_json()

    assert body["current_objects"] == []
    assert body["total_objects"] == [{"object_class": "cat", "count": 1}]


def test_predictions_endpoint_writes_nothing(store):
    with create_app().test_client() as client:
        data = {"file": (io.BytesIO(IMAGE.read_bytes()), "cat.jpg")}
        response = client.post("/object-predictions", data=data, content_type="multipart/form-data")

    assert response.status_code == 200
    assert store() == {}


def test_concurrent_requests_lose_no_updates(store):
    app = create_app()

    def one_request(_):
        with app.test_client() as client:
            return count(client).status_code

    with ThreadPoolExecutor(max_workers=10) as executor:
        statuses = list(executor.map(one_request, range(20)))

    assert statuses == [200] * 20
    assert store() == {"cat": 20}
