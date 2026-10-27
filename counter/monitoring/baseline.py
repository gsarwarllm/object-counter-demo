"""Reference baselines: the feature distributions of one model version on a reference image set.

Written by `scripts/model_registry.py baseline` (and stored with the version in MLflow), read by
the drift monitor. One JSON file per version: <BASELINES_DIR>/<model>/<version>.json.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from counter.adapters.model_manifest import REPO_ROOT
from counter.monitoring.drift import Distributions

DEFAULT_BASELINES_DIR = REPO_ROOT / "tmp" / "baselines"


@dataclass
class Baseline:
    model: str
    version: str
    created_at: str
    source: str  # where the reference images came from
    distributions: Distributions


def baseline_path(directory: Path, model: str, version: str) -> Path:
    return Path(directory) / model / f"{version}.json"


def save_baseline(baseline: Baseline, directory: Path = DEFAULT_BASELINES_DIR) -> Path:
    path = baseline_path(directory, baseline.model, baseline.version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(baseline), indent=2, sort_keys=True) + "\n")
    return path


def load_baseline(directory: Path, model: str, version: str) -> Baseline | None:
    path = baseline_path(directory, model, version)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return Baseline(
        model=data["model"],
        version=data["version"],
        created_at=data["created_at"],
        source=data["source"],
        distributions=Distributions(**data["distributions"]),
    )
