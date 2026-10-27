import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from counter.domain.actions import CountDetectedObjects, DetectObjects
from counter.domain.errors import DetectorUnavailableError
from counter.metrics import CANARY_FALLBACKS

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class Route:
    """The use cases of one served version of a model."""

    version: str | None
    count: CountDetectedObjects
    detect: DetectObjects


class ModelRoutes:
    """Which version of a model answers a request: the champion, or in a canary release the
    candidate for canary_percent % of requests (chosen per request).

    If the candidate is unavailable, the champion answers instead (counted in
    canary_fallbacks_total), so a broken candidate costs latency, not failed requests.
    """

    def __init__(
        self,
        model: str,
        champion: Route,
        canary: Route | None = None,
        canary_percent: float = 0.0,
        draw: Callable[[], float] = random.random,
    ) -> None:
        self.__model = model
        self.__champion = champion
        self.__canary = canary
        self.__canary_percent = canary_percent
        self.__draw = draw

    def run(self, call: Callable[[Route], T]) -> tuple[T, Route]:
        """Calls the chosen version's use case; returns its result and the version used."""
        canary = self.__canary
        if canary is not None and self.__draw() * 100 < self.__canary_percent:
            try:
                return call(canary), canary
            except DetectorUnavailableError as error:
                logger.warning(
                    "Canary %s@%s unavailable, the champion answers: %s",
                    self.__model,
                    canary.version,
                    error,
                )
                CANARY_FALLBACKS.labels(self.__model, canary.version or "latest").inc()
        return call(self.__champion), self.__champion
