from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageDraw, ImageFont

from counter.domain.models import Prediction
from counter.domain.ports import DebugImageWriter

FONT_FILE = Path(__file__).resolve().parent.parent / "resources" / "arial.ttf"


class FileDebugImageWriter(DebugImageWriter):
    """Draws the prediction boxes and saves a JPEG in output_dir."""

    def __init__(self, output_dir: str | Path) -> None:
        self.__output_dir = Path(output_dir)

    def write(self, image: BinaryIO, predictions: list[Prediction], image_name: str) -> None:
        image.seek(0)
        with Image.open(image) as opened_image:
            drawing = opened_image.convert("RGB")
        draw_image = ImageDraw.Draw(drawing, "RGBA")
        image_width, image_height = drawing.size
        font = ImageFont.truetype(str(FONT_FILE), 20)
        for prediction in predictions:
            box = prediction.box
            draw_image.rectangle(
                [
                    (box.xmin * image_width, box.ymin * image_height),
                    (box.xmax * image_width, box.ymax * image_height),
                ],
                outline="red",
            )
            draw_image.text(
                (
                    box.xmin * image_width,
                    box.ymin * image_height - font.getlength(prediction.class_name),
                ),
                f"{prediction.class_name}: {prediction.score}",
                font=font,
                fill="black",
            )
        self.__output_dir.mkdir(parents=True, exist_ok=True)
        drawing.save(self.__output_dir / image_name, "JPEG")
