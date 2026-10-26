import os
from pathlib import Path

from psycopg.conninfo import make_conninfo

from counter.adapters.count_repo import CountInMemoryRepo, CountMongoDBRepo, CountPostgresRepo
from counter.adapters.debug_image_writer import FileDebugImageWriter
from counter.adapters.object_detector import FakeObjectDetector, TFSObjectDetector
from counter.domain.actions import CountDetectedObjects, DetectObjects
from counter.domain.ports import DebugImageWriter, ObjectCountRepo, ObjectDetector

DEBUG_IMAGES_DIR = Path("tmp") / "debug"


def fake_object_detector() -> ObjectDetector:
    return FakeObjectDetector()


def tfs_object_detector() -> ObjectDetector:
    tfs_host = os.environ.get("TFS_HOST", "localhost")
    tfs_port = int(os.environ.get("TFS_PORT", "8501"))
    model_name = os.environ.get("MODEL_NAME", "ssd_mobilenet_v2")
    timeout = float(os.environ.get("TFS_TIMEOUT", "30"))
    return TFSObjectDetector(tfs_host, tfs_port, model_name, timeout)


OBJECT_DETECTORS = {
    "dev": fake_object_detector,
    "prod": tfs_object_detector,
}


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


def get_object_detector() -> ObjectDetector:
    """ENV picks the detector: dev = fake, prod = TF Serving."""
    env = _env()
    if env not in OBJECT_DETECTORS:
        raise ValueError(f"Unknown ENV {env!r}; expected one of {sorted(OBJECT_DETECTORS)}")
    return OBJECT_DETECTORS[env]()


def get_count_repo() -> ObjectCountRepo:
    """COUNT_REPO picks the store; defaults keep the old behaviour (dev: memory, prod: mongo)."""
    default = "mongo" if _env() == "prod" else "memory"
    repo_name = os.environ.get("COUNT_REPO", default)
    if repo_name not in COUNT_REPOS:
        raise ValueError(f"Unknown COUNT_REPO {repo_name!r}; expected one of {sorted(COUNT_REPOS)}")
    return COUNT_REPOS[repo_name]()


def get_debug_image_writer() -> DebugImageWriter | None:
    """DEBUG_IMAGES=1 saves annotated images to tmp/debug; off by default."""
    if os.environ.get("DEBUG_IMAGES") == "1":
        return FileDebugImageWriter(DEBUG_IMAGES_DIR)
    return None


def get_count_action(object_detector: ObjectDetector | None = None) -> CountDetectedObjects:
    if object_detector is None:
        object_detector = get_object_detector()
    return CountDetectedObjects(object_detector, get_count_repo(), get_debug_image_writer())


def get_detect_action(object_detector: ObjectDetector | None = None) -> DetectObjects:
    if object_detector is None:
        object_detector = get_object_detector()
    return DetectObjects(object_detector, get_debug_image_writer())


def _env() -> str:
    return os.environ.get("ENV", "dev")
