import io
import threading
from unittest.mock import Mock

import pytest
from prometheus_client import REGISTRY

from counter.adapters.shadow_detector import ShadowDetector, ShadowPool
from counter.domain.errors import DetectorUnavailableError
from counter.domain.models import Box, Prediction

BOX = Box(0, 0, 1, 1)


def prediction(class_name, score=0.9):
    return Prediction(class_name, score, BOX)


def detector(*predictions):
    fake = Mock()
    fake.predict.return_value = list(predictions)
    return fake


def shadow_count(outcome, model="m", version="2"):
    value = REGISTRY.get_sample_value(
        "shadow_requests_total", {"model": model, "version": version, "outcome": outcome}
    )
    return value or 0.0


def agreement_sum(model="m", version="2"):
    labels = {"model": model, "version": version}
    return REGISTRY.get_sample_value("shadow_class_agreement_sum", labels) or 0.0


@pytest.fixture
def pool():
    pool = ShadowPool(workers=1, max_pending=2)
    yield pool
    pool.shutdown()


def test_client_gets_the_champion_and_the_candidate_sees_the_same_image(pool):
    champion = detector(prediction("cat"))
    seen = []
    candidate = Mock()
    candidate.predict.side_effect = lambda image: seen.append(image.read()) or []
    image = io.BytesIO(b"jpeg bytes")

    result = ShadowDetector(champion, candidate, "m", "2", pool).predict(image)
    pool.shutdown()

    assert result == [prediction("cat")]
    assert seen == [b"jpeg bytes"]
    assert image.tell() == 0  # left ready for the next reader


@pytest.mark.parametrize(
    ("champion", "candidate", "expected"),
    [
        ([prediction("cat")], [prediction("cat")], 1.0),
        ([prediction("cat"), prediction("dog")], [prediction("cat")], 0.5),
        ([prediction("cat")], [prediction("cat", 0.4)], 0.0),  # below 0.5 doesn't count
        ([], [], 1.0),
    ],
)
def test_agreement_is_the_overlap_of_classes(pool, champion, candidate, expected):
    compared, total = shadow_count("compared", version="agree"), agreement_sum(version="agree")

    ShadowDetector(detector(*champion), detector(*candidate), "m", "agree", pool).predict(
        io.BytesIO(b"x")
    )
    pool.shutdown()

    assert shadow_count("compared", version="agree") == compared + 1
    assert agreement_sum(version="agree") == pytest.approx(total + expected)


def test_a_failing_candidate_is_counted_and_never_reaches_the_client(pool):
    candidate = Mock()
    candidate.predict.side_effect = DetectorUnavailableError("down")
    failed = shadow_count("failed", version="3")

    result = ShadowDetector(detector(prediction("cat")), candidate, "m", "3", pool).predict(
        io.BytesIO(b"x")
    )
    pool.shutdown()

    assert result == [prediction("cat")]
    assert shadow_count("failed", version="3") == failed + 1


def test_shadow_calls_are_dropped_when_the_pool_is_busy():
    pool = ShadowPool(workers=1, max_pending=1)
    release = threading.Event()
    candidate = Mock()
    candidate.predict.side_effect = lambda image: release.wait(5) and []
    shadow = ShadowDetector(detector(), candidate, "m", "4", pool)
    dropped = shadow_count("dropped", version="4")

    shadow.predict(io.BytesIO(b"first"))  # takes the only slot
    shadow.predict(io.BytesIO(b"second"))
    release.set()
    pool.shutdown()

    assert candidate.predict.call_count == 1
    assert shadow_count("dropped", version="4") == dropped + 1


def test_no_shadow_call_when_the_champion_fails(pool):
    champion = Mock()
    champion.predict.side_effect = DetectorUnavailableError("down")
    candidate = detector()

    with pytest.raises(DetectorUnavailableError):
        ShadowDetector(champion, candidate, "m", "2", pool).predict(io.BytesIO(b"x"))
    pool.shutdown()

    candidate.predict.assert_not_called()


def test_readiness_is_the_champions(pool):
    champion, candidate = Mock(), Mock()

    ShadowDetector(champion, candidate, "m", "2", pool).check_ready()

    champion.check_ready.assert_called_once()
    candidate.check_ready.assert_not_called()
