import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from psycopg.conninfo import make_conninfo

from counter.adapters.count_repo import CountInMemoryRepo, CountMongoDBRepo, CountPostgresRepo
from counter.adapters.debug_image_writer import FileDebugImageWriter
from counter.adapters.detector_factory import DetectorFactory
from counter.adapters.detector_registry import DetectorRegistry
from counter.adapters.model_manifest import (
    DEFAULT_LOCK,
    DEFAULT_MANIFEST,
    candidates_lock,
    load_manifest,
    read_lock,
)
from counter.adapters.prediction_log import (
    BackgroundPredictionLog,
    InMemoryPredictionLog,
    PostgresPredictionLog,
)
from counter.domain.ports import DebugImageWriter, ObjectCountRepo, PredictionLog
from counter.monitoring.baseline import DEFAULT_BASELINES_DIR

DEBUG_IMAGES_DIR = Path("tmp") / "debug"
ENVS = ("dev", "prod")


def get_detector_registry() -> DetectorRegistry:
    """One detector per model in models/models.json.

    dev: fake detectors, no TF Serving needed. prod: TF Serving, pinned to the versions
    `make pull-models` wrote to models.lock.json (startup fails if one is missing). With
    RELEASE_MODE shadow or canary, each model's candidate version (candidates.lock.json) is
    served too.
    """
    env = get_env()
    if env not in ENVS:
        raise ValueError(f"Unknown ENV {env!r}; expected one of {list(ENVS)}")
    manifest = load_manifest(Path(os.environ.get("MODELS_MANIFEST", DEFAULT_MANIFEST)))
    factory = DetectorFactory(
        tfs_host=os.environ.get("TFS_HOST", "localhost"),
        tfs_port=int(os.environ.get("TFS_PORT", "8501")),
        tfs_timeout=float(os.environ.get("TFS_TIMEOUT", "30")),
        force_serving="fake" if env == "dev" else None,
    )
    lock = Path(os.environ.get("MODELS_LOCK", DEFAULT_LOCK))
    versions = read_lock(lock) if env == "prod" else {}
    with_candidates = env == "prod" and get_release_settings().mode != "off"
    return DetectorRegistry.from_manifest(
        manifest,
        factory,
        versions,
        require_versions=env == "prod",
        candidate_versions=read_lock(candidates_lock(lock)) if with_candidates else None,
    )


RELEASE_MODES = ("off", "shadow", "canary")


@dataclass(frozen=True)
class ReleaseSettings:
    mode: str
    canary_percent: float
    shadow_workers: int
    shadow_max_pending: int


def get_release_settings() -> ReleaseSettings:
    """RELEASE_MODE: off (default), shadow (the candidate gets a background copy of each
    request) or canary (CANARY_PERCENT % of requests are answered by the candidate)."""
    mode = os.environ.get("RELEASE_MODE", "off")
    if mode not in RELEASE_MODES:
        raise ValueError(f"Unknown RELEASE_MODE {mode!r}; expected one of {list(RELEASE_MODES)}")
    canary_percent = float(os.environ.get("CANARY_PERCENT", "10"))
    if not 0 <= canary_percent <= 100:
        raise ValueError(f"CANARY_PERCENT must be between 0 and 100, got {canary_percent}")
    return ReleaseSettings(
        mode=mode,
        canary_percent=canary_percent,
        shadow_workers=int(os.environ.get("SHADOW_WORKERS", "2")),
        shadow_max_pending=int(os.environ.get("SHADOW_MAX_PENDING", "4")),
    )


def memory_count_repo() -> ObjectCountRepo:
    return CountInMemoryRepo()


def mongo_count_repo() -> ObjectCountRepo:
    mongo_host = os.environ.get("MONGO_HOST", "localhost")
    mongo_port = int(os.environ.get("MONGO_PORT", "27017"))
    mongo_db = os.environ.get("MONGO_DB", "prod_counter")
    timeout = float(os.environ.get("MONGO_TIMEOUT", "5"))
    return CountMongoDBRepo(host=mongo_host, port=mongo_port, database=mongo_db, timeout=timeout)


def postgres_count_repo() -> ObjectCountRepo:
    return CountPostgresRepo(_postgres_conninfo(), timeout=_postgres_timeout())


def _postgres_conninfo() -> str:
    return os.environ.get("DATABASE_URL") or make_conninfo(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "counter"),
        user=os.environ.get("POSTGRES_USER", "counter"),
        password=os.environ.get("POSTGRES_PASSWORD", "counter"),
    )


def _postgres_timeout() -> float:
    return float(os.environ.get("POSTGRES_TIMEOUT", "5"))


COUNT_REPOS = {
    "memory": memory_count_repo,
    "mongo": mongo_count_repo,
    "postgres": postgres_count_repo,
}


def get_count_repo() -> ObjectCountRepo:
    """COUNT_REPO picks the store; defaults keep the old behaviour (dev: memory, prod: mongo)."""
    default = "mongo" if get_env() == "prod" else "memory"
    repo_name = os.environ.get("COUNT_REPO", default)
    if repo_name not in COUNT_REPOS:
        raise ValueError(f"Unknown COUNT_REPO {repo_name!r}; expected one of {sorted(COUNT_REPOS)}")
    return COUNT_REPOS[repo_name]()


PREDICTION_LOGS = ("none", "memory", "postgres")


def get_prediction_log() -> PredictionLog | None:
    """PREDICTION_LOG picks where model outputs are logged for drift monitoring.

    Defaults: memory in dev, postgres in prod (the same database settings as COUNT_REPO=postgres,
    whatever COUNT_REPO is). Postgres writes go through a background thread.
    """
    default = "postgres" if get_env() == "prod" else "memory"
    name = os.environ.get("PREDICTION_LOG", default)
    if name not in PREDICTION_LOGS:
        raise ValueError(
            f"Unknown PREDICTION_LOG {name!r}; expected one of {list(PREDICTION_LOGS)}"
        )
    if name == "none":
        return None
    if name == "memory":
        return InMemoryPredictionLog()
    return BackgroundPredictionLog(
        PostgresPredictionLog(_postgres_conninfo(), timeout=_postgres_timeout())
    )


@dataclass(frozen=True)
class DriftSettings:
    baselines_dir: Path
    window: timedelta
    min_images: int
    cache_seconds: float


def get_drift_settings() -> DriftSettings:
    return DriftSettings(
        baselines_dir=Path(os.environ.get("BASELINES_DIR", DEFAULT_BASELINES_DIR)),
        window=timedelta(hours=float(os.environ.get("DRIFT_WINDOW_HOURS", "24"))),
        min_images=int(os.environ.get("DRIFT_MIN_IMAGES", "30")),
        cache_seconds=float(os.environ.get("DRIFT_CACHE_SECONDS", "300")),
    )


def get_debug_image_writer() -> DebugImageWriter | None:
    """DEBUG_IMAGES=1 saves annotated images to tmp/debug; off by default."""
    if os.environ.get("DEBUG_IMAGES") == "1":
        return FileDebugImageWriter(DEBUG_IMAGES_DIR)
    return None


def get_env() -> str:
    return os.environ.get("ENV", "dev")
