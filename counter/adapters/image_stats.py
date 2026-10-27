from typing import BinaryIO

from PIL import Image, ImageStat, UnidentifiedImageError

from counter.domain.models import ImageStats

# Statistics come from a small greyscale copy: enough for drift, and cheap (a JPEG is decoded
# at reduced scale).
STATS_SIZE = (256, 256)


def image_stats(image: BinaryIO) -> ImageStats | None:
    """Size, colour mode, brightness and contrast of an uploaded image; None if unreadable."""
    image.seek(0)
    try:
        with Image.open(image) as opened:
            width, height, color_mode = opened.width, opened.height, opened.mode
            opened.draft("L", STATS_SIZE)
            grey = opened.convert("L")
            grey.thumbnail(STATS_SIZE)
            stat = ImageStat.Stat(grey)
            return ImageStats(width, height, color_mode, stat.mean[0], stat.stddev[0])
    except (UnidentifiedImageError, OSError):
        return None
    finally:
        image.seek(0)
