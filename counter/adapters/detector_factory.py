from collections.abc import Callable

from counter.adapters.model_manifest import ModelSpec, load_label_map
from counter.adapters.object_detector import FakeObjectDetector, TFSObjectDetector
from counter.domain.ports import ObjectDetector


class DetectorFactory:
    """Builds the ObjectDetector for a model from its manifest entry, chosen by `serving`.

    Supporting another serving technology (e.g. ONNX Runtime, TorchServe) means adding one
    builder here and one adapter class; the registry, use cases and endpoints don't change.
    """

    def __init__(
        self,
        tfs_host: str = "localhost",
        tfs_port: int = 8501,
        tfs_timeout: float = 30.0,
        force_serving: str | None = None,
    ):
        self.__tfs_host = tfs_host
        self.__tfs_port = tfs_port
        self.__tfs_timeout = tfs_timeout
        # ENV=dev forces "fake" so every configured model works without TF Serving.
        self.__force_serving = force_serving
        self.__builders: dict[str, Callable[[ModelSpec, str | None], ObjectDetector]] = {
            "tfserving": self.__tfserving,
            "fake": self.__fake,
        }

    def create(self, spec: ModelSpec, version: str | None) -> ObjectDetector:
        serving = self.__force_serving or spec.serving
        if serving not in self.__builders:
            raise ValueError(
                f"Unknown serving type {serving!r} for model {spec.name!r}; "
                f"expected one of {sorted(self.__builders)}"
            )
        return self.__builders[serving](spec, version)

    def __tfserving(self, spec: ModelSpec, version: str | None) -> ObjectDetector:
        return TFSObjectDetector(
            self.__tfs_host,
            self.__tfs_port,
            spec.name,
            classes=load_label_map(spec.label_map),
            version=version,
            timeout=self.__tfs_timeout,
        )

    @staticmethod
    def __fake(spec: ModelSpec, version: str | None) -> ObjectDetector:
        return FakeObjectDetector()
