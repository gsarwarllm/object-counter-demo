import os

from counter.adapters.count_repo import CountMongoDBRepo, CountInMemoryRepo
from counter.adapters.object_detector import TFSObjectDetector, FakeObjectDetector
from counter.domain.actions import CountDetectedObjects, DetectObjects
from counter.domain.ports import ObjectDetector, ObjectCountRepo


def dev_object_detector() -> ObjectDetector:
    return FakeObjectDetector()


def prod_object_detector() -> ObjectDetector:
    tfs_host = os.environ.get('TFS_HOST', 'localhost')
    tfs_port = os.environ.get('TFS_PORT', 8501)
    model_name = os.environ.get('MODEL_NAME', 'ssd_mobilenet_v2')
    return TFSObjectDetector(tfs_host, tfs_port, model_name)


def dev_count_repo() -> ObjectCountRepo:
    return CountInMemoryRepo()


def prod_count_repo() -> ObjectCountRepo:
    mongo_host = os.environ.get('MONGO_HOST', 'localhost')
    mongo_port = os.environ.get('MONGO_PORT', 27017)
    mongo_db = os.environ.get('MONGO_DB', 'prod_counter')
    return CountMongoDBRepo(host=mongo_host, port=mongo_port, database=mongo_db)


def get_object_detector() -> ObjectDetector:
    return globals()[f"{_env()}_object_detector"]()


def get_count_action(object_detector: ObjectDetector = None) -> CountDetectedObjects:
    if object_detector is None:
        object_detector = get_object_detector()
    return CountDetectedObjects(object_detector, globals()[f"{_env()}_count_repo"]())


def get_detect_action(object_detector: ObjectDetector = None) -> DetectObjects:
    if object_detector is None:
        object_detector = get_object_detector()
    return DetectObjects(object_detector)


def _env() -> str:
    return os.environ.get('ENV', 'dev')
