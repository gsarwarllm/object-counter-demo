import logging
from typing import BinaryIO

import numpy as np
import requests
from PIL import Image, UnidentifiedImageError

from counter.domain.errors import DetectorUnavailableError, InvalidImageError
from counter.domain.models import Box, Prediction
from counter.domain.ports import ObjectDetector

logger = logging.getLogger(__name__)


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
        self.url = f"http://{host}:{port}/v1/models/{model}{version_path}:predict"
        self.timeout = timeout
        self.classes_dict = classes

    def predict(self, image: BinaryIO) -> list[Prediction]:
        np_image = self.__to_np_array(image)
        logger.info("Sending request to TF Serving: %s", self.url)
        try:
            response = requests.post(
                self.url,
                json={"instances": np.expand_dims(np_image, 0).tolist()},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return self.__raw_predictions_to_domain(response.json()["predictions"][0])
        except requests.RequestException as error:
            raise DetectorUnavailableError(f"TF Serving request failed: {error}") from error
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise DetectorUnavailableError(f"Unexpected TF Serving response: {error}") from error

    @staticmethod
    def __to_np_array(image: BinaryIO):
        image.seek(0)
        try:
            with Image.open(image) as opened_image:
                # RGBA and greyscale images become the 3-channel input the model expects.
                return np.asarray(opened_image.convert("RGB"), dtype=np.uint8)
        except (UnidentifiedImageError, OSError) as error:
            raise InvalidImageError("file is not a readable image") from error

    def __raw_predictions_to_domain(self, raw_predictions: dict) -> list[Prediction]:
        num_detections = int(raw_predictions.get("num_detections"))
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
        logger.info("TF Serving returned %d detections", len(predictions))
        return predictions
