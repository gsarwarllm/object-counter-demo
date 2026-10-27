from abc import ABC, abstractmethod
from datetime import datetime
from typing import BinaryIO

from counter.domain.models import ObjectCount, Prediction, PredictionRecord


class ObjectDetector(ABC):
    @abstractmethod
    def predict(self, image: BinaryIO) -> list[Prediction]:
        raise NotImplementedError

    # Not abstract: in-process detectors (fakes) are always ready.
    def check_ready(self) -> None:  # noqa: B027
        """Raises DetectorUnavailableError if predict() can't work now."""


class ObjectCountRepo(ABC):
    @abstractmethod
    def read_values(self, object_classes: list[str] | None = None) -> list[ObjectCount]:
        raise NotImplementedError

    @abstractmethod
    def update_values(self, new_values: list[ObjectCount]) -> None:
        raise NotImplementedError

    # Not abstract: in-process stores (memory) are always ready.
    def check_ready(self) -> None:  # noqa: B027
        """Raises RepositoryUnavailableError if the store can't be used now."""


class DebugImageWriter(ABC):
    """Saves an image with the prediction boxes drawn on it, for debugging."""

    @abstractmethod
    def write(self, image: BinaryIO, predictions: list[Prediction], image_name: str) -> None:
        raise NotImplementedError


class PredictionLog(ABC):
    """Stores what the models predicted, so drift can be measured later."""

    @abstractmethod
    def append(self, record: PredictionRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def read(self, model: str, version: str, since: datetime) -> list[PredictionRecord]:
        """Records of one model version logged at or after `since`, oldest first."""
        raise NotImplementedError
