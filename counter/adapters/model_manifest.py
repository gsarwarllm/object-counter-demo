"""Reads models/models.json (which models exist) and models.lock.json (which versions are pulled).

Standard library only: the model registry scripts in scripts/ use it too.
"""

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "models" / "models.json"
DEFAULT_LOCK = REPO_ROOT / "tmp" / "model" / "models.lock.json"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    serving: str
    label_map: Path
    registry_alias: str
    source_url: str | None = None
    description: str = ""


@dataclass(frozen=True)
class ModelManifest:
    default_model: str
    models: tuple[ModelSpec, ...]

    def get(self, name: str) -> ModelSpec:
        for spec in self.models:
            if spec.name == name:
                return spec
        raise KeyError(name)

    @property
    def names(self) -> list[str]:
        return [spec.name for spec in self.models]


def load_manifest(path: Path = DEFAULT_MANIFEST) -> ModelManifest:
    """Parses and validates the manifest; label map paths are relative to the manifest file."""
    data = json.loads(Path(path).read_text())
    specs = tuple(
        ModelSpec(
            name=entry["name"],
            serving=entry["serving"],
            label_map=(Path(path).parent / entry["label_map"]).resolve(),
            registry_alias=entry.get("registry_alias", "champion"),
            source_url=entry.get("source_url"),
            description=entry.get("description", ""),
        )
        for entry in data["models"]
    )
    names = [spec.name for spec in specs]
    if not specs:
        raise ValueError(f"{path}: no models defined")
    if len(set(names)) != len(names):
        raise ValueError(f"{path}: duplicate model names in {names}")
    if data["default_model"] not in names:
        raise ValueError(f"{path}: default_model {data['default_model']!r} is not in {names}")
    return ModelManifest(default_model=data["default_model"], models=specs)


def load_label_map(path: Path) -> dict[int, str]:
    """Class id -> display name, from a label map in the TF Object Detection JSON format."""
    labels = json.loads(Path(path).read_text())
    return {int(label["id"]): label["display_name"] for label in labels}


def read_lock(path: Path = DEFAULT_LOCK) -> dict[str, str]:
    """Model name -> version pulled from the registry (written by `make pull-models`)."""
    if not Path(path).exists():
        return {}
    return {name: str(version) for name, version in json.loads(Path(path).read_text()).items()}


def write_lock(versions: dict[str, str], path: Path = DEFAULT_LOCK):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(versions, indent=2, sort_keys=True) + "\n")
