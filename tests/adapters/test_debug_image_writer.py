import io

from PIL import Image

from counter.adapters.debug_image_writer import FileDebugImageWriter
from counter.domain.models import Box, Prediction


def test_writes_annotated_jpeg(tmp_path):
    image = io.BytesIO()
    Image.new("RGBA", (20, 10)).save(image, "PNG")
    image.seek(5)  # the writer must not depend on the stream position
    predictions = [Prediction("cat", 0.9, Box(0.1, 0.1, 0.5, 0.5))]

    FileDebugImageWriter(tmp_path / "debug").write(image, predictions, "out.jpg")

    with Image.open(tmp_path / "debug" / "out.jpg") as written:
        assert written.format == "JPEG"
        assert written.size == (20, 10)
