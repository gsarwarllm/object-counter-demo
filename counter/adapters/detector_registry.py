from dataclasses import dataclass

from counter.adapters.detector_factory import DetectorFactory
from counter.adapters.model_manifest import ModelManifest
from counter.domain.ports import ObjectDetector


@dataclass(frozen=True)
class ServedModel:
    name: str
    version: str | None
    detector: ObjectDetector


class DetectorRegistry:
    """The models this app serves, one detector each, built once at startup."""

    def __init__(self, models: list[ServedModel], default_model: str):
        self.__models = {model.name: model for model in models}
        if default_model not in self.__models:
            raise ValueError(f"Default model {default_model!r} is not in {self.names}")
        self.__default_model = default_model

    @classmethod
    def from_manifest(
        cls,
        manifest: ModelManifest,
        factory: DetectorFactory,
        versions: dict[str, str],
        require_versions: bool,
    ) -> "DetectorRegistry":
        """Fails fast: a model without a pulled version stops startup with a clear message."""
        missing = [name for name in manifest.names if name not in versions]
        if require_versions and missing:
            raise ValueError(
                f"No pulled version for models {missing} in models.lock.json; "
                "run `make pull-models`"
            )
        models = [
            ServedModel(
                spec.name, versions.get(spec.name), factory.create(spec, versions.get(spec.name))
            )
            for spec in manifest.models
        ]
        return cls(models, manifest.default_model)

    @property
    def names(self) -> list[str]:
        return sorted(self.__models)

    @property
    def default_model(self) -> str:
        return self.__default_model

    @property
    def models(self) -> list[ServedModel]:
        return list(self.__models.values())

    def get(self, name: str | None = None) -> ServedModel:
        """The named model, or the default one; KeyError if the name is unknown."""
        return self.__models[name or self.__default_model]
