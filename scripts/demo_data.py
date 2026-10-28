"""Demo data for the monitoring dashboard: every drift state at once, without real traffic.

    python scripts/demo_data.py --demo [--reset] [--requests N] [--url URL]

For a local stack only. For each served model version (models.lock.json and candidates.lock.json,
or "latest" when nothing is pulled) it writes a synthetic "healthy" baseline to BASELINES_DIR and
logs synthetic predictions to PostgreSQL's prediction_logs, spread over the drift window:

- ssd_mobilenet_v2: drift on every feature. It turns into a night camera (dark, low-contrast
  greyscale 1280x720 images) and the model loses confidence: fewer detections, other classes.
- acme_shelf_detector: moderate drift in brightness and classes, stable elsewhere.
- candidate versions (and any other model): stable.

Fixed seeds, so every run gives the same statuses. --requests N also sends N real requests (some
of them invalid) to the app, for the traffic, latency, error and release panels; their images
are logged too, so they can move the statuses a little. --reset first deletes every row of
prediction_logs. Without --demo the script refuses to run.
"""

import argparse
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from counter import config
from counter.adapters.model_manifest import (
    DEFAULT_LOCK,
    DEFAULT_MANIFEST,
    REPO_ROOT,
    ModelManifest,
    candidates_lock,
    load_manifest,
    read_lock,
)
from counter.adapters.prediction_log import PostgresPredictionLog
from counter.domain.models import ImageStats, PredictionRecord
from counter.domain.ports import PredictionLog
from counter.monitoring.baseline import Baseline, save_baseline
from counter.monitoring.drift import distributions

BASELINE_IMAGES = 1000
WINDOW_IMAGES = 500
# Scores per image: TF Serving returns a fixed number of detections, most of them unlikely.
SCORES_PER_IMAGE = 20
BASELINE_SEED = 1
WINDOW_SEED = 2
SAMPLE_IMAGES = REPO_ROOT / "resources" / "images"


@dataclass(frozen=True)
class Profile:
    """How synthetic images and the model's answers to them are distributed."""

    name: str
    sizes: dict[tuple[int, int], float]  # (width, height) -> weight
    brightness: tuple[float, float]  # mean and standard deviation of mean luminance
    contrast: tuple[float, float]
    color_modes: dict[str, float]
    detections: Sequence[float]  # weights of 0, 1, 2, ... confident detections per image
    confident_scores: tuple[float, float]  # uniform range of scores at or above 0.5
    other_scores: tuple[float, float]  # uniform range of the remaining scores
    classes: dict[str, float] = field(
        default_factory=lambda: {
            "person": 0.35,
            "car": 0.12,
            "chair": 0.1,
            "cup": 0.08,
            "bottle": 0.08,
            "book": 0.08,
            "bicycle": 0.07,
            "dog": 0.06,
            "cat": 0.06,
        }
    )


HEALTHY = Profile(
    name="stable",
    sizes={
        (640, 480): 0.35,
        (1280, 960): 0.2,
        (1920, 1080): 0.2,
        (800, 800): 0.1,
        (4032, 3024): 0.1,
        (320, 240): 0.05,
    },
    brightness=(125.0, 30.0),
    contrast=(58.0, 12.0),
    color_modes={"RGB": 0.9, "RGBA": 0.05, "P": 0.05},
    detections=[0.05, 0.25, 0.25, 0.2, 0.1, 0.08, 0.04, 0.02, 0.01],
    confident_scores=(0.55, 0.98),
    other_scores=(0.01, 0.45),
)
NIGHT_CAMERA = Profile(
    name="night camera: drift on every feature",
    sizes={(1280, 720): 1.0},
    brightness=(38.0, 10.0),
    contrast=(14.0, 5.0),
    color_modes={"L": 1.0},
    detections=[0.4, 0.35, 0.15, 0.07, 0.03],
    confident_scores=(0.5, 0.7),
    other_scores=(0.2, 0.49),
    classes={"car": 0.4, "truck": 0.25, "person": 0.2, "traffic light": 0.15},
)
SLIGHTLY_DARKER_SHELVES = replace(
    HEALTHY,
    name="darker shelves: moderate brightness and classes drift",
    brightness=(112.0, 30.0),
    classes=HEALTHY.classes | {"bottle": 0.18, "cup": 0.15, "person": 0.22},
)
SCENARIOS = {
    "ssd_mobilenet_v2": NIGHT_CAMERA,
    "acme_shelf_detector": SLIGHTLY_DARKER_SHELVES,
}


@dataclass(frozen=True)
class ServedVersion:
    model: str
    version: str
    role: str  # champion | candidate


def served_versions(manifest: ModelManifest, lock_path: Path = DEFAULT_LOCK) -> list[ServedVersion]:
    """The versions the app serves and the drift monitor checks; "latest" when none is pulled."""
    pulled = read_lock(lock_path)
    candidates = read_lock(candidates_lock(lock_path))
    return [
        ServedVersion(name, pulled.get(name, "latest"), "champion") for name in manifest.names
    ] + [ServedVersion(name, version, "candidate") for name, version in sorted(candidates.items())]


def scenario(served: ServedVersion) -> Profile:
    if served.role == "candidate":
        return HEALTHY
    return SCENARIOS.get(served.model, HEALTHY)


def generate(
    profile: Profile,
    model: str,
    version: str,
    count: int,
    seed: int,
    start: datetime,
    end: datetime,
) -> list[PredictionRecord]:
    """count records whose logged_at is spread evenly from start to end."""
    rng = random.Random(seed)  # nosec B311
    step = (end - start) / max(count, 1)
    return [_record(profile, model, version, start + step * i, rng) for i in range(count)]


def seed(
    log: PredictionLog,
    versions: list[ServedVersion],
    baselines_dir: Path,
    window: timedelta,
    now: datetime | None = None,
) -> list[str]:
    """Writes each version's healthy baseline and logs its scenario; one line per version."""
    now = now or datetime.now(UTC)
    start = now - window * 0.95  # all rows well inside the window the monitor reads
    lines = []
    for served in versions:
        reference = generate(
            HEALTHY, served.model, served.version, BASELINE_IMAGES, BASELINE_SEED, start, now
        )
        save_baseline(
            Baseline(
                model=served.model,
                version=served.version,
                created_at=now.isoformat(),
                source=f"demo data ({BASELINE_IMAGES} synthetic images)",
                distributions=distributions(reference),
            ),
            baselines_dir,
        )
        profile = scenario(served)
        for record in generate(
            profile, served.model, served.version, WINDOW_IMAGES, WINDOW_SEED, start, now
        ):
            log.append(record)
        lines.append(
            f"{served.model}@{served.version} ({served.role}): {WINDOW_IMAGES} predictions, "
            f"{profile.name}"
        )
    return lines


def send_requests(url: str, count: int, seed_value: int = WINDOW_SEED) -> dict[int, int]:
    """Sends count requests with the sample images, every tenth one invalid; returns
    responses per status code."""
    import requests  # only needed with --requests

    rng = random.Random(seed_value)  # nosec B311
    images = sorted(SAMPLE_IMAGES.glob("*.jpg"))
    models = [model["name"] for model in requests.get(f"{url}/models", timeout=10).json()["models"]]
    statuses: dict[int, int] = {}
    for i in range(count):
        path = rng.choice(["/object-count", "/object-predictions"])
        data = {"threshold": str(round(rng.uniform(0.3, 0.9), 2)), "model_name": rng.choice(models)}
        image = rng.choice(images)
        files = {"file": (image.name, image.read_bytes(), "image/jpeg")}
        if i % 10 == 9:  # invalid: threshold out of range, not an image, unknown model
            kind = (i // 10) % 3
            if kind == 0:
                data["threshold"] = "1.5"
            elif kind == 1:
                files = {"file": ("notes.txt", b"not an image", "text/plain")}
            else:
                data["model_name"] = "no_such_model"
        response = requests.post(f"{url}{path}", data=data, files=files, timeout=60)
        statuses[response.status_code] = statuses.get(response.status_code, 0) + 1
    return statuses


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Demo data for the monitoring dashboard")
    parser.add_argument(
        "--demo", action="store_true", help="confirms this is a demo stack (required)"
    )
    parser.add_argument("--reset", action="store_true", help="delete every prediction_logs row")
    parser.add_argument("--requests", type=int, default=0, help="also send N requests to the app")
    parser.add_argument("--url", default="http://localhost:5000", help="the app, for --requests")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    args = parser.parse_args(argv)
    if not args.demo:
        print(
            "Refusing to run without --demo: this writes synthetic predictions and replaces the "
            "drift baselines. Use it on a local demo stack only (make demo-data).",
            file=sys.stderr,
        )
        return 2
    settings = config.get_drift_settings()
    versions = served_versions(load_manifest(args.manifest), args.lock)
    log = PostgresPredictionLog(config.postgres_conninfo(), timeout=config.postgres_timeout())
    try:
        if args.reset:
            deleted = log.purge(datetime.now(UTC) + timedelta(days=1))
            print(f"Deleted {deleted} prediction_logs rows")
        for line in seed(log, versions, settings.baselines_dir, settings.window):
            print(line)
    finally:
        log.close()
    print(
        f"Baselines written to {settings.baselines_dir} (make pull-models restores the real ones)"
    )
    if args.requests:
        import requests

        try:
            statuses = send_requests(args.url.rstrip("/"), args.requests)
        except requests.ConnectionError:
            print(f"The app isn't reachable at {args.url}; start it or pass --url", file=sys.stderr)
            return 1
        print(f"Sent {args.requests} requests to {args.url}: {dict(sorted(statuses.items()))}")
    print("Check with `make drift`, or the Grafana dashboard once DRIFT_CACHE_SECONDS have passed")
    return 0


def _record(
    profile: Profile, model: str, version: str, logged_at: datetime, rng: random.Random
) -> PredictionRecord:
    width, height = _choice(rng, profile.sizes)
    confident = rng.choices(range(len(profile.detections)), weights=profile.detections)[0]
    class_names = list(profile.classes)
    scores = [rng.uniform(*profile.confident_scores) for _ in range(confident)] + [
        rng.uniform(*profile.other_scores) for _ in range(SCORES_PER_IMAGE - confident)
    ]
    classes = [_choice(rng, profile.classes) for _ in range(confident)] + [
        rng.choice(class_names) for _ in range(SCORES_PER_IMAGE - confident)
    ]
    stats = ImageStats(
        width=width,
        height=height,
        color_mode=_choice(rng, profile.color_modes),
        brightness=_clip(rng.gauss(*profile.brightness), 0.0, 255.0),
        contrast=_clip(rng.gauss(*profile.contrast), 0.0, 128.0),
    )
    return PredictionRecord(model, version, logged_at, scores, classes, stats)


def _choice[T](rng: random.Random, weights: dict[T, float]) -> T:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


if __name__ == "__main__":
    sys.exit(main())
