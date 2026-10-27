from datetime import UTC, datetime

from counter.domain.models import ImageStats, PredictionRecord


def record(scores, classes=None, model="m", version="1", logged_at=None, image=None):
    return PredictionRecord(
        model=model,
        version=version,
        logged_at=logged_at or datetime.now(UTC),
        scores=list(scores),
        classes=list(classes) if classes is not None else ["cat"] * len(scores),
        image=image,
    )


def photo(width=640, height=480, mode="RGB", brightness=110.0, contrast=50.0):
    return ImageStats(width, height, mode, brightness, contrast)


def daylight_uploads(images):
    """Typical traffic: 640x480 colour photos of average brightness and contrast."""
    return [record([0.9], image=photo()) for _ in range(images)]


def confident_cats(images):
    """A healthy model: two confident cats and some low-score noise per image."""
    return [record([0.95, 0.9, 0.2, 0.05], ["cat", "cat", "dog", "cup"]) for _ in range(images)]


def unsure_model(images):
    """The same scenes, but the model lost confidence: scores slide below the threshold."""
    return [record([0.55, 0.45, 0.2, 0.05], ["cat", "cat", "dog", "cup"]) for _ in range(images)]
