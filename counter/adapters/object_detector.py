import logging
import time
from typing import BinaryIO

import numpy as np
import requests
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

from counter.domain.errors import DetectorUnavailableError, InvalidImageError
from counter.domain.models import Box, Prediction
from counter.domain.ports import ObjectDetector

logger = logging.getLogger(__name__)
# Seconds; status checks back readiness probes, which must answer quickly.
STATUS_TIMEOUT = 3.0


class FakeObjectDetector(ObjectDetector):
    def predict(self, image: BinaryIO) -> list[Prediction]:
        return [
            Prediction(
                class_name="cat",
                score=0.999190748,
                box=Box(xmin=0.367288858, ymin=0.278333426, xmax=0.735821366, ymax=0.6988855),
            ),
        ]


class TFSObjectDetector(ObjectDetector):
    """Calls TF Serving's REST API; classes maps the model's class ids to names."""

    def __init__(
        self,
        host: str,
        port: int,
        model: str,
        classes: dict[int, str],
        version: str | None = None,
        timeout: float = 30.0,
    ):
        # A pinned version makes responses traceable to an exact model version.
        version_path = f"/versions/{version}" if version else ""
        self.status_url = f"http://{host}:{port}/v1/models/{model}{version_path}"
        self.url = f"{self.status_url}:predict"
        self.model_label = f"{model}@{version or 'latest'}"
        self.timeout = timeout
        self.status_timeout = min(timeout, STATUS_TIMEOUT)
        self.classes_dict = classes

    def predict(self, image: BinaryIO) -> list[Prediction]:
        np_image = self.__to_np_array(image)
        logger.debug("Sending request to TF Serving: %s", self.url)
        started = time.perf_counter()
        try:
            response = requests.post(
                self.url,
                json={"instances": np.expand_dims(np_image, 0).tolist()},
                timeout=self.timeout,
            )
            response.raise_for_status()
            predictions = self.__raw_predictions_to_domain(response.json()["predictions"][0])
        except requests.RequestException as error:
            raise DetectorUnavailableError(
                f"TF Serving request for {self.model_label} failed: {error}"
            ) from error
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise DetectorUnavailableError(
                f"Unexpected TF Serving response for {self.model_label}: {error}"
            ) from error
        logger.info(
            "%s returned %d detections in %.0f ms",
            self.model_label,
            len(predictions),
            (time.perf_counter() - started) * 1000,
        )
        return predictions

    def check_ready(self) -> None:
        """Asks TF Serving for the model's status; ready only if a version is AVAILABLE."""
        try:
            response = requests.get(self.status_url, timeout=self.status_timeout)
            response.raise_for_status()
            states = [status["state"] for status in response.json()["model_version_status"]]
        except requests.RequestException as error:
            raise DetectorUnavailableError(
                f"TF Serving status for {self.model_label} failed: {error}"
            ) from error
        except (ValueError, KeyError, TypeError) as error:
            raise DetectorUnavailableError(
                f"Unexpected TF Serving status for {self.model_label}: {error}"
            ) from error
        if "AVAILABLE" not in states:
            raise DetectorUnavailableError(f"{self.model_label} is not available: {states}")

    @staticmethod
    def __to_np_array(image: BinaryIO) -> NDArray[np.uint8]:
        image.seek(0)
        try:
            with Image.open(image) as opened_image:
                # RGBA and greyscale images become the 3-channel input the model expects.
                return np.asarray(opened_image.convert("RGB"), dtype=np.uint8)
        except (UnidentifiedImageError, OSError) as error:
            raise InvalidImageError("file is not a readable image") from error

    def __raw_predictions_to_domain(self, raw_predictions: dict) -> list[Prediction]:
        num_detections = int(raw_predictions["num_detections"])
        predictions = []
        for i in range(num_detections):
            detection_box = raw_predictions["detection_boxes"][i]
            box = Box(
                xmin=detection_box[1],
                ymin=detection_box[0],
                xmax=detection_box[3],
                ymax=detection_box[2],
            )
            detection_score = raw_predictions["detection_scores"][i]
            detection_class = int(raw_predictions["detection_classes"][i])
            class_name = self.classes_dict.get(detection_class, f"unknown_{detection_class}")
            predictions.append(Prediction(class_name=class_name, score=detection_score, box=box))
        return predictions
