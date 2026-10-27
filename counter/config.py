import os
from pathlib import Path

from psycopg.conninfo import make_conninfo

from counter.adapters.count_repo import CountInMemoryRepo, CountMongoDBRepo, CountPostgresRepo
from counter.adapters.debug_image_writer import FileDebugImageWriter
from counter.adapters.detector_factory import DetectorFactory
from counter.adapters.detector_registry import DetectorRegistry
from counter.adapters.model_manifest import DEFAULT_LOCK, DEFAULT_MANIFEST, load_manifest, read_lock
from counter.domain.ports import DebugImageWriter, ObjectCountRepo

DEBUG_IMAGES_DIR = Path("tmp") / "debug"
ENVS = ("dev", "prod")


def get_detector_registry() -> DetectorRegistry:
    """One detector per model in models/models.json.

    dev: fake detectors, no TF Serving needed. prod: TF Serving, pinned to the versions
    `make pull-models` wrote to models.lock.json (startup fails if one is missing).
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
    versions = read_lock(Path(os.environ.get("MODELS_LOCK", DEFAULT_LOCK))) if env == "prod" else {}
    return DetectorRegistry.from_manifest(
        manifest, factory, versions, require_versions=env == "prod"
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
    conninfo = os.environ.get("DATABASE_URL") or make_conninfo(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "counter"),
        user=os.environ.get("POSTGRES_USER", "counter"),
        password=os.environ.get("POSTGRES_PASSWORD", "counter"),
    )
    timeout = float(os.environ.get("POSTGRES_TIMEOUT", "5"))
    return CountPostgresRepo(conninfo, timeout=timeout)


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


def get_debug_image_writer() -> DebugImageWriter | None:
    """DEBUG_IMAGES=1 saves annotated images to tmp/debug; off by default."""
    if os.environ.get("DEBUG_IMAGES") == "1":
        return FileDebugImageWriter(DEBUG_IMAGES_DIR)
    return None


def get_env() -> str:
    return os.environ.get("ENV", "dev")
