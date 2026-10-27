import time
from datetime import UTC, datetime
from typing import BinaryIO

from counter.adapters.image_stats import image_stats
from counter.domain.errors import DetectorUnavailableError, InvalidImageError
from counter.domain.models import Prediction, PredictionRecord
from counter.domain.ports import ObjectDetector, PredictionLog
from counter.metrics import DETECTOR_LATENCY, DETECTOR_REQUESTS


class InstrumentedDetector(ObjectDetector):
    """Wraps a detector: records the duration and outcome of every call per model version, and
    logs what the model returned (all scores and classes) for drift monitoring.

    A decorator, so neither the domain nor the TF Serving adapter knows about monitoring.
    """

    def __init__(
        self,
        detector: ObjectDetector,
        model: str,
        version: str | None,
        prediction_log: PredictionLog | None = None,
    ) -> None:
        self.__detector = detector
        self.__labels = {"model": model, "version": version or "latest"}
        self.__prediction_log = prediction_log

    def predict(self, image: BinaryIO) -> list[Prediction]:
        outcome = "error"
        started = time.perf_counter()
        try:
            predictions = self.__detector.predict(image)
            outcome = "ok"
            self.__log(image, predictions)
            return predictions
        except DetectorUnavailableError:
            outcome = "unavailable"
            raise
        except InvalidImageError:
            outcome = "invalid_image"
            raise
        finally:
            DETECTOR_LATENCY.labels(**self.__labels).observe(time.perf_counter() - started)
            DETECTOR_REQUESTS.labels(**self.__labels, outcome=outcome).inc()

    def check_ready(self) -> None:
        self.__detector.check_ready()

    def __log(self, image: BinaryIO, predictions: list[Prediction]) -> None:
        if self.__prediction_log is None:
            return
        self.__prediction_log.append(
            PredictionRecord(
                model=self.__labels["model"],
                version=self.__labels["version"],
                logged_at=datetime.now(UTC),
                scores=[float(prediction.score) for prediction in predictions],
                classes=[prediction.class_name for prediction in predictions],
                image=image_stats(image),
            )
        )
