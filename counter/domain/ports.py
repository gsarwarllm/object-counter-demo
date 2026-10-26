from abc import ABC, abstractmethod
from typing import BinaryIO

from counter.domain.models import ObjectCount, Prediction


class ObjectDetector(ABC):
    @abstractmethod
    def predict(self, image: BinaryIO) -> list[Prediction]:
        raise NotImplementedError


class ObjectCountRepo(ABC):
    @abstractmethod
    def read_values(self, object_classes: list[str] | None = None) -> list[ObjectCount]:
        raise NotImplementedError

    @abstractmethod
    def update_values(self, new_values: list[ObjectCount]):
        raise NotImplementedError


class DebugImageWriter(ABC):
    """Saves an image with the prediction boxes drawn on it, for debugging."""

    @abstractmethod
    def write(self, image: BinaryIO, predictions: list[Prediction], image_name: str):
        raise NotImplementedError
