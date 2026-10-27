import io
import logging
import re
from unittest.mock import Mock

import numpy as np
import pytest
import requests
from PIL import Image

from counter.adapters.model_manifest import REPO_ROOT, load_label_map
from counter.adapters.object_detector import TFSObjectDetector
from counter.domain.errors import DetectorUnavailableError, InvalidImageError
from counter.domain.models import Box, Prediction

TFS_RESPONSE = {
    "predictions": [
        {
            "num_detections": 2.0,
            "detection_boxes": [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]],
            "detection_scores": [0.9, 0.4],
            "detection_classes": [17.0, 47.0],
        }
    ]
}


def png_bytes(mode: str, size=(4, 3)) -> io.BytesIO:
    buffer = io.BytesIO()
    Image.new(mode, size).save(buffer, "PNG")
    buffer.seek(0)
    return buffer


@pytest.fixture
def post(monkeypatch) -> Mock:
    response = Mock()
    response.json.return_value = TFS_RESPONSE
    post = Mock(return_value=response)
    monkeypatch.setattr(requests, "post", post)
    return post


COCO_LABELS = load_label_map(REPO_ROOT / "models" / "labels" / "mscoco.json")


@pytest.fixture
def detector():
    return TFSObjectDetector("tfs", 8501, "ssd_mobilenet_v2", COCO_LABELS, version="3", timeout=7)


def sent_image(post: Mock) -> np.ndarray:
    return np.array(post.call_args.kwargs["json"]["instances"][0])


def test_maps_tf_serving_output_to_predictions(detector, post):
    predictions = detector.predict(png_bytes("RGB"))

    assert predictions == [
        Prediction("cat", 0.9, Box(xmin=0.2, ymin=0.1, xmax=0.4, ymax=0.3)),
        Prediction("cup", 0.4, Box(xmin=0.6, ymin=0.5, xmax=0.8, ymax=0.7)),
    ]
    assert post.call_args.args[0] == "http://tfs:8501/v1/models/ssd_mobilenet_v2/versions/3:predict"
    assert post.call_args.kwargs["timeout"] == 7


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "P"])
def test_sends_three_channel_image_for_any_mode(detector, post, mode):
    detector.predict(png_bytes(mode, size=(4, 3)))

    assert sent_image(post).shape == (3, 4, 3)


def test_unknown_class_id_gets_a_placeholder_name(detector, post):
    post.return_value.json.return_value = {
        "predictions": [
            {
                "num_detections": 1,
                "detection_boxes": [[0, 0, 1, 1]],
                "detection_scores": [0.5],
                "detection_classes": [999],
            }
        ]
    }

    assert detector.predict(png_bytes("RGB"))[0].class_name == "unknown_999"


def test_undecodable_image_raises_invalid_image(detector, post):
    with pytest.raises(InvalidImageError):
        detector.predict(io.BytesIO(b"not an image"))
    post.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [requests.ConnectionError("refused"), requests.Timeout("too slow")],
)
def test_connection_failures_raise_detector_unavailable(detector, post, failure):
    post.side_effect = failure

    with pytest.raises(DetectorUnavailableError):
        detector.predict(png_bytes("RGB"))


def test_http_error_raises_detector_unavailable(detector, post):
    post.return_value.raise_for_status.side_effect = requests.HTTPError("500 Server Error")

    with pytest.raises(DetectorUnavailableError):
        detector.predict(png_bytes("RGB"))


def test_malformed_response_raises_detector_unavailable(detector, post):
    post.return_value.json.return_value = {"error": "model not found"}

    with pytest.raises(DetectorUnavailableError):
        detector.predict(png_bytes("RGB"))


def test_without_version_calls_the_latest_model(post):
    TFSObjectDetector("tfs", 8501, "ssd_mobilenet_v2", COCO_LABELS).predict(png_bytes("RGB"))

    assert post.call_args.args[0] == "http://tfs:8501/v1/models/ssd_mobilenet_v2:predict"


def test_uses_the_injected_label_map(post):
    detector = TFSObjectDetector("tfs", 8501, "custom", {17: "price_tag", 47: "shelf"})

    assert [p.class_name for p in detector.predict(png_bytes("RGB"))] == ["price_tag", "shelf"]


def test_logs_model_detections_and_duration(detector, post, caplog):
    with caplog.at_level(logging.DEBUG, logger="counter.adapters.object_detector"):
        detector.predict(png_bytes("RGB"))

    info = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    debug = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(info) == 1
    assert re.fullmatch(r"ssd_mobilenet_v2@3 returned 2 detections in \d+ ms", info[0])
    assert debug == ["Sending request to TF Serving: " + post.call_args.args[0]]


def test_failure_message_names_the_model(detector, post):
    post.side_effect = requests.ConnectionError("refused")

    with pytest.raises(DetectorUnavailableError, match="ssd_mobilenet_v2@3 failed: refused"):
        detector.predict(png_bytes("RGB"))
