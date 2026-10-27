import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import BinaryIO

from counter.domain.models import Prediction
from counter.domain.ports import ObjectDetector
from counter.metrics import SHADOW_AGREEMENT, SHADOW_REQUESTS

logger = logging.getLogger(__name__)

# Classes found at this score are compared (the same cut as the drift features).
AGREEMENT_THRESHOLD = 0.5


class ShadowPool:
    """Background threads for shadow calls, shared by every model of an app.

    At most max_pending calls wait or run at once; beyond that a shadow call is dropped, so a
    slow candidate can never build up a queue. The threads start on first use, in the process
    that serves requests.
    """

    def __init__(self, workers: int = 2, max_pending: int = 4) -> None:
        self.__workers = workers
        self.__slots = threading.BoundedSemaphore(max_pending)
        self.__lock = threading.Lock()
        self.__executor: ThreadPoolExecutor | None = None

    def submit(self, task: "ShadowTask") -> bool:
        """Runs a task in the background; False (task dropped) when max_pending are in flight."""
        if not self.__slots.acquire(blocking=False):
            return False
        try:
            with self.__lock:
                if self.__executor is None:
                    self.__executor = ThreadPoolExecutor(
                        self.__workers, thread_name_prefix="shadow"
                    )
                self.__executor.submit(self.__run, task)
        except BaseException:
            self.__slots.release()
            raise
        return True

    def __run(self, task: "ShadowTask") -> None:
        try:
            task.run()
        finally:
            self.__slots.release()

    def shutdown(self) -> None:
        """Waits for the calls in flight (tests)."""
        with self.__lock:
            if self.__executor is not None:
                self.__executor.shutdown(wait=True)
                self.__executor = None


class ShadowTask:
    def __init__(
        self,
        candidate: ObjectDetector,
        image: bytes,
        champion_predictions: list[Prediction],
        labels: dict[str, str],
    ) -> None:
        self.__candidate = candidate
        self.__image = image
        self.__champion_classes = _classes(champion_predictions)
        self.__labels = labels

    def run(self) -> None:
        try:
            predictions = self.__candidate.predict(BytesIO(self.__image))
        except Exception as error:  # a shadow call never affects the request; it's only counted
            logger.warning("Shadow call to %s@%s failed: %s", *self.__labels.values(), error)
            SHADOW_REQUESTS.labels(**self.__labels, outcome="failed").inc()
            return
        SHADOW_REQUESTS.labels(**self.__labels, outcome="compared").inc()
        SHADOW_AGREEMENT.labels(**self.__labels).observe(
            _agreement(self.__champion_classes, _classes(predictions))
        )


class ShadowDetector(ObjectDetector):
    """Answers with the champion; sends a copy of each image to the candidate in the background.

    The candidate is usually an InstrumentedDetector, so its latency, outcome and predictions are
    recorded under its own version (metrics, prediction log, drift) without the client seeing it.
    """

    def __init__(
        self,
        champion: ObjectDetector,
        candidate: ObjectDetector,
        model: str,
        candidate_version: str,
        pool: ShadowPool,
    ) -> None:
        self.__champion = champion
        self.__candidate = candidate
        self.__labels = {"model": model, "version": candidate_version}
        self.__pool = pool

    def predict(self, image: BinaryIO) -> list[Prediction]:
        predictions = self.__champion.predict(image)
        image.seek(0)
        task = ShadowTask(self.__candidate, image.read(), predictions, self.__labels)
        image.seek(0)
        if not self.__pool.submit(task):
            SHADOW_REQUESTS.labels(**self.__labels, outcome="dropped").inc()
        return predictions

    def check_ready(self) -> None:
        self.__champion.check_ready()


def _classes(predictions: list[Prediction]) -> set[str]:
    return {p.class_name for p in predictions if p.score >= AGREEMENT_THRESHOLD}


def _agreement(champion: set[str], candidate: set[str]) -> float:
    """Jaccard index; two empty sets agree completely."""
    union = champion | candidate
    return len(champion & candidate) / len(union) if union else 1.0
