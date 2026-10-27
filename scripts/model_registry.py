"""Model registry workflow: download -> publish (MLflow) -> pull (TF Serving layout) -> baseline.

    python scripts/model_registry.py download            # stand-in for "training output"
    python scripts/model_registry.py publish [--model NAME] [--downloads DIR]   # new versions
    python scripts/model_registry.py pull                # alias -> version -> tmp/model/
    python scripts/model_registry.py promote NAME VERSION|candidate [--alias champion] [--force]
    python scripts/model_registry.py baseline [--images DIR] [--no-registry]
    python scripts/model_registry.py evaluate NAME VERSION [--dataset FILE] [--min-f1 X]

Releasing a new version safely: publish it, point the "candidate" alias at it (promote --alias
candidate), pull (TF Serving then loads the champion and the candidate; the app still calls the
champion unless RELEASE_MODE is shadow or canary), evaluate it, then promote it to champion: that
refuses a version that wasn't evaluated or scores worse than the champion on the same evaluation
set (--force overrides, and records it).

`download` needs only the standard library. The others need MLflow
(requirements-models.txt, installed by `make setup-models`); `baseline` also needs TF Serving
serving the pulled versions (`make up`), and `--no-registry` skips MLflow. The registry is a local
SQLite database plus an artifact folder under tmp/mlflow/; point MLFLOW_TRACKING_URI at a
company MLflow server to use the same commands against a private registry.
"""

import argparse
import dataclasses
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from counter.adapters.model_manifest import (
    DEFAULT_LOCK,
    DEFAULT_MANIFEST,
    REPO_ROOT,
    ModelManifest,
    ModelSpec,
    candidates_lock,
    load_label_map,
    load_manifest,
    read_lock,
    write_lock,
)
from counter.domain.models import PredictionRecord
from counter.monitoring import evaluation as quality
from counter.monitoring.baseline import DEFAULT_BASELINES_DIR, Baseline, save_baseline
from counter.monitoring.drift import distributions

DOWNLOADS_DIR = REPO_ROOT / "tmp" / "downloads"
MODEL_DIR = REPO_ROOT / "tmp" / "model"
MLFLOW_DIR = REPO_ROOT / "tmp" / "mlflow"
DEFAULT_TRACKING_URI = f"sqlite:///{MLFLOW_DIR / 'registry.db'}"
EXPERIMENT = "model-publishing"
SAVED_MODEL_FILE = "saved_model.pb"
# Reference images for baselines. The three samples only demonstrate the workflow; point
# --images at a real validation set (hundreds of images like the production traffic).
REFERENCE_IMAGES = REPO_ROOT / "resources" / "images"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
BASELINE_ARTIFACT_DIR = "baseline"
EVALUATION_ARTIFACT_DIR = "evaluation"
# Promotion to this alias goes through the quality gate; "candidate" versions are served next to
# the champion, for evaluation and for shadow or canary releases (RELEASE_MODE, X6).
GATED_ALIAS = "champion"
CANDIDATE_ALIAS = "candidate"


def download(manifest: ModelManifest, downloads_dir: Path = DOWNLOADS_DIR) -> None:
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


def _extract_saved_model(archive: Path, target: Path) -> None:
    """Extracts the <archive root>/saved_model/ folder into target."""
    with tarfile.open(archive) as tar, tempfile.TemporaryDirectory() as tmp:
        tar.extractall(tmp, filter="data")
        found = sorted(Path(tmp).glob(f"**/saved_model/{SAVED_MODEL_FILE}"))
        if not found:
            raise ValueError(f"{archive}: no saved_model/{SAVED_MODEL_FILE} in the archive")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(found[0].parent, target, dirs_exist_ok=True)


def publish(
    manifest: ModelManifest, downloads_dir: Path = DOWNLOADS_DIR, model: str | None = None
) -> None:
    """Registers each downloaded model (or only `model`) as a new MLflow version, unless identical
    to one already registered. A model's first version also gets the manifest's registry_alias."""
    mlflow, client = _mlflow()
    experiment_id = _experiment_id(mlflow, client)
    for spec in [manifest.get(model)] if model else manifest.models:
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


def promote(
    name: str,
    version: str,
    alias: str,
    force: bool = False,
    tolerance: float = quality.DEFAULT_TOLERANCE,
) -> None:
    """Points an alias at a version: how a new model version is released or rolled back.

    Promotion to the champion alias is gated (see `quality.gate`); force overrides the gate,
    e.g. for an urgent rollback, and records that on the version. version "candidate" means the
    version the candidate alias points at (after a canary check, X6)."""
    from mlflow.exceptions import MlflowException

    _, client = _mlflow()
    if version == CANDIDATE_ALIAS:
        version = str(client.get_model_version_by_alias(name, CANDIDATE_ALIAS).version)
    candidate = client.get_model_version(name, version)  # fails clearly if it doesn't exist
    if alias == GATED_ALIAS:
        try:
            champion = client.get_model_version_by_alias(name, GATED_ALIAS)
        except MlflowException:
            champion = None
        if champion is not None and str(champion.version) == str(version):
            print(f"{name}: version {version} already is the {alias}")
            return
        decision = quality.gate(
            _float_tag(candidate, "eval_f1"),
            candidate.tags.get("eval_fingerprint"),
            _float_tag(champion, "eval_f1") if champion else None,
            champion.tags.get("eval_fingerprint") if champion else None,
            tolerance,
        )
        if not decision.allowed and not force:
            raise ValueError(
                f"{name} v{version} not promoted: {decision.reason} (--force overrides)"
            )
        if not decision.allowed:
            client.set_model_version_tag(name, version, "promoted_without_gate", decision.reason)
        outcome = "passed" if decision.allowed else "overridden"
        print(f"{name}: quality gate {outcome}: {decision.reason}")
    client.set_registered_model_alias(name, alias, version)
    print(f"{name}: alias {alias!r} -> version {version}; run pull to serve it")
    if alias == GATED_ALIAS:
        try:
            if str(client.get_model_version_by_alias(name, CANDIDATE_ALIAS).version) == str(
                version
            ):
                client.delete_registered_model_alias(name, CANDIDATE_ALIAS)
        except MlflowException:
            pass


def evaluate(
    manifest: ModelManifest,
    name: str,
    version: str,
    dataset: Path = quality.DEFAULT_EVALUATION_SET,
    register: bool = True,
) -> quality.Evaluation:
    """Scores a version served by TF Serving on a labelled evaluation set. With register, the
    metrics become tags and metrics of the version, and a model card is stored with it."""
    from counter.adapters.object_detector import TFSObjectDetector

    spec = manifest.get(name)
    evaluation_set = quality.load_evaluation_set(dataset)
    detector = TFSObjectDetector(
        os.environ.get("TFS_HOST", "localhost"),
        int(os.environ.get("TFS_PORT", "8501")),
        name,
        load_label_map(spec.label_map),
        version=version,
        timeout=float(os.environ.get("TFS_TIMEOUT", "60")),
    )
    detected = {}
    for image in evaluation_set.images:
        with open(image, "rb") as file:
            detected[image.name] = {
                prediction.class_name
                for prediction in detector.predict(file)
                if prediction.score >= quality.EVALUATION_THRESHOLD
            }
    result = quality.evaluate(evaluation_set, detected)
    print(
        f"{name} v{version} on {result.dataset} ({result.images} images): "
        f"precision {result.precision:.3f}, recall {result.recall:.3f}, F1 {result.f1:.3f}"
    )
    if register:
        _register_evaluation(spec, version, result)
    return result


def _register_evaluation(spec: ModelSpec, version: str, result: quality.Evaluation) -> None:
    _, client = _mlflow()
    model_version = client.get_model_version(spec.name, version)
    metrics = {
        "eval_f1": result.f1,
        "eval_precision": result.precision,
        "eval_recall": result.recall,
    }
    tags = {
        **metrics,
        "eval_dataset": result.dataset,
        "eval_fingerprint": result.fingerprint,
        "eval_images": result.images,
    }
    for key, value in tags.items():
        client.set_model_version_tag(spec.name, version, key, str(value))
    for key, metric in metrics.items():
        client.log_metric(model_version.run_id, key, metric)
    card = quality.model_card(spec.name, version, spec.description, spec.source_url or "", result)
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "model_card.md").write_text(card)
        (Path(tmp) / f"{result.dataset}.json").write_text(
            json.dumps(dataclasses.asdict(result), indent=2, sort_keys=True) + "\n"
        )
        client.log_artifacts(model_version.run_id, tmp, artifact_path=EVALUATION_ARTIFACT_DIR)
    print(f"{spec.name}: stored the evaluation and a model card with version {version}")


def _float_tag(model_version: Any, key: str) -> float | None:
    value = model_version.tags.get(key)
    return float(value) if value is not None else None


def pull(
    manifest: ModelManifest,
    model_dir: Path = MODEL_DIR,
    lock_path: Path = DEFAULT_LOCK,
    baselines_dir: Path = DEFAULT_BASELINES_DIR,
) -> None:
    """Resolves each model's alias to a version, downloads it into the TF Serving layout
    (model_dir/<name>/<version>/), and writes model_config.config, models.lock.json and
    candidates.lock.json (each model's candidate version, if any). A version's drift baseline, if
    `baseline` stored one, goes to baselines_dir."""
    from mlflow.exceptions import MlflowException

    mlflow, client = _mlflow()
    versions: dict[str, str] = {}
    candidates: dict[str, str] = {}
    served: dict[str, list[str]] = {}
    for spec in manifest.models:
        version = client.get_model_version_by_alias(spec.name, spec.registry_alias)
        to_serve = [version]
        try:
            candidate = client.get_model_version_by_alias(spec.name, CANDIDATE_ALIAS)
            if str(candidate.version) != str(version.version):
                to_serve.append(candidate)
                candidates[spec.name] = str(candidate.version)
        except MlflowException:
            pass  # no candidate under evaluation
        for model_version in to_serve:
            _pull_version(mlflow, spec.name, model_version, model_dir, baselines_dir)
        versions[spec.name] = str(version.version)  # MLflow 3 returns an int
        served[spec.name] = sorted({str(v.version) for v in to_serve}, key=int)
    # Created even when empty: Docker would otherwise create the mounted folder as root.
    baselines_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model_config.config").write_text(tf_serving_config(served))
    write_lock(versions, lock_path)
    # Always written, so the app never reads a stale candidate after it was promoted.
    write_lock(candidates, candidates_lock(lock_path))
    print(f"Wrote {model_dir / 'model_config.config'}, {lock_path} and its candidates lock")


def _pull_version(
    mlflow: Any, name: str, version: Any, model_dir: Path, baselines_dir: Path
) -> None:
    number = str(version.version)
    target = model_dir / name / number
    if (target / SAVED_MODEL_FILE).exists():
        print(f"{name}: version {number} already pulled")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            downloaded = mlflow.artifacts.download_artifacts(
                artifact_uri=version.source, dst_path=tmp
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(downloaded, target, dirs_exist_ok=True)
        print(f"{name}: pulled version {number} into {target}")
    _pull_baseline(mlflow, version.run_id, baselines_dir / name)


def baseline(
    manifest: ModelManifest,
    images_dir: Path = REFERENCE_IMAGES,
    lock_path: Path = DEFAULT_LOCK,
    baselines_dir: Path = DEFAULT_BASELINES_DIR,
    register: bool = True,
) -> None:
    """Runs the reference images through each pulled model version (champion and candidate) in TF
    Serving and saves the distributions the drift monitor compares production traffic with. With
    register, they're also stored with the version's run in MLflow, so `pull` brings them along."""
    # numpy, requests, Pillow: imported here so `download` keeps needing the standard library only
    from counter.adapters.image_stats import image_stats
    from counter.adapters.object_detector import TFSObjectDetector

    versions = read_lock(lock_path)
    missing = [name for name in manifest.names if name not in versions]
    if missing:
        raise ValueError(f"No pulled version for {missing}; run pull (and make up) first")
    images = sorted(path for path in images_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        raise ValueError(f"No .jpg/.jpeg/.png images in {images_dir}")
    host = os.environ.get("TFS_HOST", "localhost")
    port = int(os.environ.get("TFS_PORT", "8501"))
    timeout = float(os.environ.get("TFS_TIMEOUT", "60"))
    candidates = read_lock(candidates_lock(lock_path))
    served = [(spec, versions[spec.name]) for spec in manifest.models] + [
        (manifest.get(name), version) for name, version in sorted(candidates.items())
    ]
    for spec, version in served:
        detector = TFSObjectDetector(
            host, port, spec.name, load_label_map(spec.label_map), version=version, timeout=timeout
        )
        now = datetime.now(UTC)
        records = []
        for image in images:
            with open(image, "rb") as file:
                predictions = detector.predict(file)
                stats = image_stats(file)
            records.append(
                PredictionRecord(
                    spec.name,
                    version,
                    now,
                    [prediction.score for prediction in predictions],
                    [prediction.class_name for prediction in predictions],
                    stats,
                )
            )
        result = Baseline(
            model=spec.name,
            version=version,
            created_at=now.isoformat(),
            source=f"{images_dir} ({len(images)} images)",
            distributions=distributions(records),
        )
        path = save_baseline(result, baselines_dir)
        print(f"{spec.name}: baseline for version {version} from {len(images)} images -> {path}")
        if register:
            _, client = _mlflow()
            run_id = client.get_model_version(spec.name, version).run_id
            client.log_artifact(run_id, str(path), artifact_path=BASELINE_ARTIFACT_DIR)
            print(f"{spec.name}: stored the baseline with version {version} in the registry")


def tf_serving_config(versions: dict[str, list[str]]) -> str:
    """TF Serving model config that serves exactly these versions of each model (the pinned
    champion, plus a candidate under evaluation)."""
    entries = [
        "  config {\n"
        f'    name: "{name}"\n'
        f'    base_path: "/models/{name}"\n'
        '    model_platform: "tensorflow"\n'
        "    model_version_policy { specific { "
        + " ".join(f"versions: {number}" for number in numbers)
        + " } }\n"
        "  }\n"
        for name, numbers in sorted(versions.items())
    ]
    return (
        "# Generated by `make pull-models`; do not edit.\nmodel_config_list {\n"
        + "".join(entries)
        + "}\n"
    )


def _mlflow() -> tuple[Any, Any]:
    # MLflow is optional (own venv) and untyped here, so its objects are Any.
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow
    from mlflow import MlflowClient

    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)
    if tracking_uri == DEFAULT_TRACKING_URI:
        MLFLOW_DIR.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(tracking_uri)
    return mlflow, MlflowClient()


def _experiment_id(mlflow: Any, client: Any) -> str:
    experiment = client.get_experiment_by_name(EXPERIMENT)
    if experiment is not None:
        return str(experiment.experiment_id)
    artifacts = os.environ.get("MLFLOW_ARTIFACTS_DIR", str(MLFLOW_DIR / "artifacts"))
    return str(mlflow.create_experiment(EXPERIMENT, artifact_location=Path(artifacts).as_uri()))


def _ensure_registered_model(client: Any, spec: ModelSpec) -> None:
    from mlflow.exceptions import MlflowException

    try:
        client.get_registered_model(spec.name)
    except MlflowException:
        client.create_registered_model(spec.name, description=spec.description)


def _pull_baseline(mlflow: Any, run_id: str | None, target_dir: Path) -> None:
    """Copies the version's baseline (if `baseline` stored one) into target_dir."""
    if not run_id:
        return
    with tempfile.TemporaryDirectory() as tmp:
        try:
            downloaded = Path(
                mlflow.artifacts.download_artifacts(
                    run_id=run_id, artifact_path=BASELINE_ARTIFACT_DIR, dst_path=tmp
                )
            )
        except Exception:  # MLflow raises different errors per store when nothing was logged
            return
        target_dir.mkdir(parents=True, exist_ok=True)
        for file in downloaded.glob("*.json"):
            shutil.copy(file, target_dir / file.name)
            print(f"{target_dir.name}: pulled baseline {file.name}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("download", help="download the models listed in the manifest")
    publish_parser = commands.add_parser(
        "publish", help="register downloaded models in the MLflow registry"
    )
    publish_parser.add_argument("--model", help="only this model")
    publish_parser.add_argument("--downloads", type=Path, default=DOWNLOADS_DIR)
    commands.add_parser("pull", help="pull each model's aliased version for TF Serving")
    promote_parser = commands.add_parser("promote", help="point an alias at a model version")
    promote_parser.add_argument("name")
    promote_parser.add_argument("version", help='a version number, or "candidate"')
    promote_parser.add_argument("--alias", default="champion")
    promote_parser.add_argument(
        "--force", action="store_true", help="promote to champion even if the quality gate fails"
    )
    evaluate_parser = commands.add_parser(
        "evaluate", help="score a served version on a labelled evaluation set"
    )
    evaluate_parser.add_argument("name")
    evaluate_parser.add_argument("version")
    evaluate_parser.add_argument("--dataset", type=Path, default=quality.DEFAULT_EVALUATION_SET)
    evaluate_parser.add_argument("--no-registry", action="store_true", help="only print")
    evaluate_parser.add_argument(
        "--min-f1", type=float, help="exit 1 if F1 is below this (an absolute floor, e.g. in CI)"
    )
    baseline_parser = commands.add_parser(
        "baseline", help="compute each pulled version's drift baseline from reference images"
    )
    baseline_parser.add_argument("--images", type=Path, default=REFERENCE_IMAGES)
    baseline_parser.add_argument(
        "--no-registry", action="store_true", help="only write tmp/baselines, skip MLflow"
    )
    args = parser.parse_args()

    if args.command == "promote":
        promote(args.name, args.version, args.alias, force=args.force)
        return
    if args.command == "evaluate":
        result = evaluate(
            load_manifest(args.manifest),
            args.name,
            args.version,
            args.dataset,
            register=not args.no_registry,
        )
        if args.min_f1 is not None and result.f1 < args.min_f1:
            sys.exit(f"{args.name} v{args.version}: F1 {result.f1:.3f} is below {args.min_f1}")
        return
    if args.command == "publish":
        publish(load_manifest(args.manifest), args.downloads, args.model)
        return
    if args.command == "baseline":
        baseline(load_manifest(args.manifest), args.images, register=not args.no_registry)
        return
    manifest = load_manifest(args.manifest)
    commands_by_name: dict[str, Callable[[ModelManifest], None]] = {
        "download": download,
        "pull": pull,
    }
    commands_by_name[args.command](manifest)


if __name__ == "__main__":
    main()
