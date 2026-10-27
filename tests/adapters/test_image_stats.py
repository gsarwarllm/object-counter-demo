import io

import pytest
from PIL import Image

from counter.adapters.image_stats import image_stats


def encoded(mode, size=(400, 300), color=None, image_format="PNG"):
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, image_format)
    buffer.seek(0)
    return buffer


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "P"])
def test_keeps_the_uploaded_size_and_mode(mode):
    stats = image_stats(encoded(mode))

    assert (stats.width, stats.height, stats.color_mode) == (400, 300, mode)


def test_brightness_and_contrast_of_a_flat_image():
    stats = image_stats(encoded("L", color=200))

    assert stats.brightness == pytest.approx(200)
    assert stats.contrast == pytest.approx(0)


def test_large_jpegs_keep_their_full_size():
    stats = image_stats(encoded("RGB", size=(4000, 3000), color=(10, 20, 30), image_format="JPEG"))

    assert (stats.width, stats.height) == (4000, 3000)  # measured on a reduced decode


def test_leaves_the_stream_at_the_start_and_survives_garbage():
    stream = encoded("RGB")

    image_stats(stream)

    assert stream.tell() == 0
    assert image_stats(io.BytesIO(b"not an image")) is None
