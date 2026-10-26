"""Model registry workflow: download -> publish (MLflow) -> pull (TF Serving layout).

    python scripts/model_registry.py download            # stand-in for "training output"
    python scripts/model_registry.py publish             # register new versions in MLflow
    python scripts/model_registry.py pull                # alias -> version -> tmp/model/
    python scripts/model_registry.py promote NAME VERSION [--alias champion]

`download` needs only the standard library. The others need MLflow
(requirements-models.txt, installed by `make setup-models`). The registry is a local
SQLite database plus an artifact folder under tmp/mlflow/; point MLFLOW_TRACKING_URI at a
company MLflow server to use the same commands against a private registry.
"""

import argparse
import hashlib
import os
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from counter.adapters.model_manifest import (
    DEFAULT_LOCK,
    DEFAULT_MANIFEST,
    REPO_ROOT,
    ModelManifest,
    ModelSpec,
    load_manifest,
    write_lock,
)

DOWNLOADS_DIR = REPO_ROOT / "tmp" / "downloads"
MODEL_DIR = REPO_ROOT / "tmp" / "model"
MLFLOW_DIR = REPO_ROOT / "tmp" / "mlflow"
DEFAULT_TRACKING_URI = f"sqlite:///{MLFLOW_DIR / 'registry.db'}"
EXPERIMENT = "model-publishing"
SAVED_MODEL_FILE = "saved_model.pb"


def download(manifest: ModelManifest, downloads_dir: Path = DOWNLOADS_DIR):
    """Fetches each model's SavedModel from its source_url; skips models already downloaded."""
    for spec in manifest.models:
        target = downloads_dir / spec.name
        if (target / SAVED_MODEL_FILE).exists():
            print(f"{spec.name}: already downloaded, skipping")
            continue
        if not spec.source_url:
            raise ValueError(f"{spec.name}: no source_url in the manifest")
        if urlparse(spec.source_url).scheme not in ("http", "https", "file"):
            raise ValueError(f"{spec.name}: unsupported URL {spec.source_url!r}")
        print(f"{spec.name}: downloading {spec.source_url}")
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "model.tar.gz"
            # The URL scheme was checked above, so bandit's B310 warning doesn't apply.
            urllib.request.urlretrieve(spec.source_url, archive)  # nosec B310
            _extract_saved_model(archive, target)
        print(f"{spec.name}: saved to {target}")


def _extract_saved_model(archive: Path, target: Path):
    """Extracts the <archive root>/saved_model/ folder into target."""
    with tarfile.open(archive) as tar, tempfile.TemporaryDirectory() as tmp:
        tar.extractall(tmp, filter="data")
        found = sorted(Path(tmp).glob(f"**/saved_model/{SAVED_MODEL_FILE}"))
        if not found:
            raise ValueError(f"{archive}: no saved_model/{SAVED_MODEL_FILE} in the archive")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(found[0].parent, target, dirs_exist_ok=True)


def publish(manifest: ModelManifest, downloads_dir: Path = DOWNLOADS_DIR):
    """Registers each downloaded model as a new MLflow version, unless identical to one already
    registered. A model's first version also gets the manifest's registry_alias."""
    mlflow, client = _mlflow()
    experiment_id = _experiment_id(mlflow, client)
    for spec in manifest.models:
        source = downloads_dir / spec.name
        if not (source / SAVED_MODEL_FILE).exists():
            raise FileNotFoundError(f"{spec.name}: {source} is missing; run download first")
        digest = _sha256(source / SAVED_MODEL_FILE)
        _ensure_registered_model(client, spec)
        existing = client.search_model_versions(f"name='{spec.name}' and tag.sha256='{digest}'")
        if existing:
            print(f"{spec.name}: identical to version {existing[0].version}, skipping")
            continue
        with mlflow.start_run(experiment_id=experiment_id, run_name=f"publish-{spec.name}") as run:
            mlflow.log_artifacts(str(source), artifact_path="saved_model")
        version = client.create_model_version(
            spec.name,
            source=f"{run.info.artifact_uri}/saved_model",
            run_id=run.info.run_id,
            tags={"sha256": digest, "source_url": spec.source_url or ""},
        )
        print(f"{spec.name}: registered version {version.version}")
        if spec.registry_alias not in client.get_registered_model(spec.name).aliases:
            client.set_registered_model_alias(spec.name, spec.registry_alias, version.version)
            print(f"{spec.name}: alias {spec.registry_alias!r} -> version {version.version}")


def promote(name: str, version: str, alias: str):
    """Points an alias at a version: how a new model version is released or rolled back."""
    _, client = _mlflow()
    client.get_model_version(name, version)  # fails clearly if the version doesn't exist
    client.set_registered_model_alias(name, alias, version)
    print(f"{name}: alias {alias!r} -> version {version}; run pull to serve it")


def pull(
    manifest: ModelManifest,
    model_dir: Path = MODEL_DIR,
    lock_path: Path = DEFAULT_LOCK,
):
    """Resolves each model's alias to a version, downloads it into the TF Serving layout
    (model_dir/<name>/<version>/), and writes model_config.config and models.lock.json."""
    mlflow, client = _mlflow()
    versions = {}
    for spec in manifest.models:
        version = client.get_model_version_by_alias(spec.name, spec.registry_alias)
        number = str(version.version)  # MLflow 3 returns an int
        target = model_dir / spec.name / number
        if (target / SAVED_MODEL_FILE).exists():
            print(f"{spec.name}: version {number} already pulled")
        else:
            with tempfile.TemporaryDirectory() as tmp:
                downloaded = mlflow.artifacts.download_artifacts(
                    artifact_uri=version.source, dst_path=tmp
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(downloaded, target, dirs_exist_ok=True)
            print(f"{spec.name}: pulled version {number} into {target}")
        versions[spec.name] = number
    (model_dir / "model_config.config").write_text(tf_serving_config(versions))
    write_lock(versions, lock_path)
    print(f"Wrote {model_dir / 'model_config.config'} and {lock_path}")


def tf_serving_config(versions: dict[str, str]) -> str:
    """TF Serving model config that serves exactly the pinned version of each model."""
    entries = [
        "  config {\n"
        f'    name: "{name}"\n'
        f'    base_path: "/models/{name}"\n'
        '    model_platform: "tensorflow"\n'
        f"    model_version_policy {{ specific {{ versions: {version} }} }}\n"
        "  }\n"
        for name, version in sorted(versions.items())
    ]
    return (
        "# Generated by `make pull-models`; do not edit.\nmodel_config_list {\n"
        + "".join(entries)
        + "}\n"
    )


def _mlflow():
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow
    from mlflow import MlflowClient

    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)
    if tracking_uri == DEFAULT_TRACKING_URI:
        MLFLOW_DIR.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(tracking_uri)
    return mlflow, MlflowClient()


def _experiment_id(mlflow, client) -> str:
    experiment = client.get_experiment_by_name(EXPERIMENT)
    if experiment is not None:
        return experiment.experiment_id
    artifacts = os.environ.get("MLFLOW_ARTIFACTS_DIR", str(MLFLOW_DIR / "artifacts"))
    return mlflow.create_experiment(EXPERIMENT, artifact_location=Path(artifacts).as_uri())


def _ensure_registered_model(client, spec: ModelSpec):
    from mlflow.exceptions import MlflowException

    try:
        client.get_registered_model(spec.name)
    except MlflowException:
        client.create_registered_model(spec.name, description=spec.description)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("download", help="download the models listed in the manifest")
    commands.add_parser("publish", help="register downloaded models in the MLflow registry")
    commands.add_parser("pull", help="pull each model's aliased version for TF Serving")
    promote_parser = commands.add_parser("promote", help="point an alias at a model version")
    promote_parser.add_argument("name")
    promote_parser.add_argument("version")
    promote_parser.add_argument("--alias", default="champion")
    args = parser.parse_args()

    if args.command == "promote":
        promote(args.name, args.version, args.alias)
        return
    manifest = load_manifest(args.manifest)
    {"download": download, "publish": publish, "pull": pull}[args.command](manifest)


if __name__ == "__main__":
    main()
