import io
import json
import shutil
import tarfile

import pytest

from counter.adapters.model_manifest import (
    REPO_ROOT,
    candidates_lock,
    load_manifest,
    read_lock,
    write_lock,
)
from counter.monitoring.baseline import load_baseline
from scripts import model_registry
from tests.integration.stub_tf_serving import StubTFServing


def write_manifest(tmp_path, source_url=None, alias="champion"):
    (tmp_path / "labels.json").write_text('[{"id": 1, "display_name": "person"}]')
    path = tmp_path / "models.json"
    model = {"name": "tiny", "serving": "tfserving", "label_map": "labels.json"}
    model |= {"registry_alias": alias, "source_url": source_url}
    path.write_text(json.dumps({"default_model": "tiny", "models": [model]}))
    return load_manifest(path)


def write_archive(path, weights=b"weights", with_saved_model=True):
    """A model-zoo style archive: <root>/saved_model/{saved_model.pb, variables/}."""
    with tarfile.open(path, "w:gz") as tar:
        files = {"tiny_model/frozen_inference_graph.pb": b"frozen"}
        if with_saved_model:
            files |= {
                "tiny_model/saved_model/saved_model.pb": weights,
                "tiny_model/saved_model/variables/variables.index": b"index",
            }
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return path


def write_saved_model(directory, weights=b"weights"):
    (directory / "variables").mkdir(parents=True, exist_ok=True)
    (directory / "saved_model.pb").write_bytes(weights)
    (directory / "variables" / "variables.index").write_bytes(b"index")


class TestDownload:
    def test_extracts_the_saved_model(self, tmp_path):
        archive = write_archive(tmp_path / "model.tar.gz")
        manifest = write_manifest(tmp_path, source_url=archive.as_uri())

        model_registry.download(manifest, tmp_path / "downloads")

        target = tmp_path / "downloads" / "tiny"
        assert (target / "saved_model.pb").read_bytes() == b"weights"
        assert (target / "variables" / "variables.index").exists()
        assert not (target / "frozen_inference_graph.pb").exists()

    def test_skips_models_already_downloaded(self, tmp_path):
        write_saved_model(tmp_path / "downloads" / "tiny", b"existing")
        manifest = write_manifest(tmp_path, source_url="https://example.invalid/never-fetched")

        model_registry.download(manifest, tmp_path / "downloads")

        assert (tmp_path / "downloads" / "tiny" / "saved_model.pb").read_bytes() == b"existing"

    def test_rejects_unsupported_url_schemes(self, tmp_path):
        manifest = write_manifest(tmp_path, source_url="ftp://example.invalid/model.tar.gz")

        with pytest.raises(ValueError, match="unsupported URL"):
            model_registry.download(manifest, tmp_path / "downloads")

    def test_rejects_archives_without_a_saved_model(self, tmp_path):
        archive = write_archive(tmp_path / "model.tar.gz", with_saved_model=False)
        manifest = write_manifest(tmp_path, source_url=archive.as_uri())

        with pytest.raises(ValueError, match="no saved_model"):
            model_registry.download(manifest, tmp_path / "downloads")


def test_tf_serving_config_pins_each_version():
    config = model_registry.tf_serving_config({"b_model": ["7"], "a_model": ["2", "3"]})

    assert config.index('name: "a_model"') < config.index('name: "b_model"')
    assert 'base_path: "/models/a_model"' in config
    assert "model_version_policy { specific { versions: 2 versions: 3 } }" in config
    assert "model_version_policy { specific { versions: 7 } }" in config


def coco_manifest(tmp_path):
    """The tiny model, but with the COCO label map: the stub answers cat, dog and person."""
    path = tmp_path / "coco_models.json"
    label_map = REPO_ROOT / "models" / "labels" / "mscoco.json"
    model = {"name": "tiny", "serving": "tfserving", "label_map": str(label_map)}
    path.write_text(json.dumps({"default_model": "tiny", "models": [model]}))
    return load_manifest(path)


def evaluation_set(tmp_path, labels):
    for name in labels:
        shutil.copy(model_registry.REFERENCE_IMAGES / "cat.jpg", tmp_path / name)
    path = tmp_path / "evaluation.json"
    path.write_text(json.dumps({"name": "test_set", "images_dir": ".", "labels": labels}))
    return path


@pytest.fixture
def tf_serving(monkeypatch):
    stub = StubTFServing().start()
    monkeypatch.setenv("TFS_HOST", "127.0.0.1")
    monkeypatch.setenv("TFS_PORT", str(stub.port))
    yield stub
    stub.stop()


class TestBaseline:
    """baseline against a stub TF Serving, without the registry."""

    def test_runs_every_reference_image_through_the_pinned_version(self, tmp_path, tf_serving):
        manifest = write_manifest(tmp_path)
        write_lock({"tiny": "3"}, tmp_path / "models.lock.json")

        model_registry.baseline(
            manifest,
            lock_path=tmp_path / "models.lock.json",
            baselines_dir=tmp_path / "baselines",
            register=False,
        )

        result = load_baseline(tmp_path / "baselines", "tiny", "3")
        images = len(list(model_registry.REFERENCE_IMAGES.glob("*.jpg")))
        assert result.distributions.images == result.distributions.input_images == images
        assert sum(result.distributions.detections) == images
        assert result.distributions.color_mode == {"RGB": images}
        assert {request["path"] for request in tf_serving.requests} == {
            "/v1/models/tiny/versions/3:predict"
        }

    def test_evaluate_scores_the_served_version(self, tmp_path, tf_serving):
        dataset = evaluation_set(tmp_path, {"a.jpg": ["cat"], "b.jpg": ["cat", "person"]})

        result = model_registry.evaluate(coco_manifest(tmp_path), "tiny", "4", dataset, False)

        # the stub detects cat (0.97) and dog (0.64) in every image; person (0.12) is too low
        assert (result.precision, result.recall, result.f1) == (0.5, 0.6667, 0.5714)
        assert {request["path"] for request in tf_serving.requests} == {
            "/v1/models/tiny/versions/4:predict"
        }

    def test_covers_the_candidate_version_too(self, tmp_path, tf_serving):
        manifest = write_manifest(tmp_path)
        write_lock({"tiny": "3"}, tmp_path / "models.lock.json")
        write_lock({"tiny": "4"}, candidates_lock(tmp_path / "models.lock.json"))

        model_registry.baseline(
            manifest,
            lock_path=tmp_path / "models.lock.json",
            baselines_dir=tmp_path / "baselines",
            register=False,
        )

        assert load_baseline(tmp_path / "baselines", "tiny", "4") is not None
        assert {request["path"] for request in tf_serving.requests} == {
            "/v1/models/tiny/versions/3:predict",
            "/v1/models/tiny/versions/4:predict",
        }

    def test_needs_pulled_versions(self, tmp_path):
        with pytest.raises(ValueError, match="No pulled version"):
            model_registry.baseline(write_manifest(tmp_path), lock_path=tmp_path / "none.json")

    def test_needs_reference_images(self, tmp_path):
        write_lock({"tiny": "3"}, tmp_path / "models.lock.json")
        (tmp_path / "empty").mkdir()

        with pytest.raises(ValueError, match=r"No \.jpg/\.jpeg/\.png images"):
            model_registry.baseline(
                write_manifest(tmp_path), tmp_path / "empty", tmp_path / "models.lock.json"
            )


@pytest.mark.models
class TestRegistry:
    """publish -> pull -> promote against a throwaway MLflow registry (SQLite + local folder)."""

    @pytest.fixture(autouse=True)
    def registry(self, tmp_path, monkeypatch):
        pytest.importorskip("mlflow")
        monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path / 'registry.db'}")
        monkeypatch.setenv("MLFLOW_ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    @pytest.fixture
    def manifest(self, tmp_path):
        return write_manifest(tmp_path)

    def publish(self, tmp_path, manifest, weights):
        write_saved_model(tmp_path / "downloads" / "tiny", weights)
        model_registry.publish(manifest, tmp_path / "downloads")

    def pull(self, tmp_path, manifest):
        model_registry.pull(
            manifest,
            tmp_path / "model",
            tmp_path / "model" / "models.lock.json",
            tmp_path / "baselines",
        )
        return read_lock(tmp_path / "model" / "models.lock.json")

    def candidates(self, tmp_path):
        return candidates_lock(tmp_path / "model" / "models.lock.json")

    def test_publish_can_take_one_model_from_another_folder(self, tmp_path, manifest):
        from mlflow import MlflowClient

        self.publish(tmp_path, manifest, b"v1 weights")
        write_saved_model(tmp_path / "retrained" / "tiny", b"retrained weights")

        model_registry.publish(manifest, tmp_path / "retrained", model="tiny")

        versions = MlflowClient().search_model_versions("name='tiny'")
        assert sorted(str(version.version) for version in versions) == ["1", "2"]

    def test_publish_then_pull_writes_the_tf_serving_layout(self, tmp_path, manifest):
        self.publish(tmp_path, manifest, b"v1 weights")

        assert self.pull(tmp_path, manifest) == {"tiny": "1"}
        version_dir = tmp_path / "model" / "tiny" / "1"
        assert (version_dir / "saved_model.pb").read_bytes() == b"v1 weights"
        assert (version_dir / "variables" / "variables.index").exists()
        config = (tmp_path / "model" / "model_config.config").read_text()
        assert "model_version_policy { specific { versions: 1 } }" in config

    def test_publishing_identical_weights_twice_keeps_one_version(self, tmp_path, manifest):
        from mlflow import MlflowClient

        self.publish(tmp_path, manifest, b"same weights")
        self.publish(tmp_path, manifest, b"same weights")

        versions = MlflowClient().search_model_versions("name='tiny'")
        assert [str(version.version) for version in versions] == ["1"]

    def test_new_version_is_served_only_after_promotion(self, tmp_path, manifest):
        self.publish(tmp_path, manifest, b"v1 weights")
        self.publish(tmp_path, manifest, b"v2 weights")

        assert self.pull(tmp_path, manifest) == {"tiny": "1"}  # alias still on version 1

        self.evaluated("1", 0.8)
        self.evaluated("2", 0.8)
        model_registry.promote("tiny", "2", "champion")

        assert self.pull(tmp_path, manifest) == {"tiny": "2"}
        assert (tmp_path / "model" / "tiny" / "2" / "saved_model.pb").read_bytes() == b"v2 weights"

    def test_promote_rejects_unknown_versions(self, tmp_path, manifest):
        from mlflow.exceptions import MlflowException

        self.publish(tmp_path, manifest, b"v1 weights")

        with pytest.raises(MlflowException):
            model_registry.promote("tiny", "9", "champion")

    def test_baseline_is_stored_with_the_version_and_pulled_with_it(
        self, tmp_path, manifest, tf_serving
    ):
        self.publish(tmp_path, manifest, b"v1 weights")
        self.pull(tmp_path, manifest)
        assert (tmp_path / "baselines").is_dir()  # created even before any baseline exists

        model_registry.baseline(
            manifest,
            lock_path=tmp_path / "model" / "models.lock.json",
            baselines_dir=tmp_path / "computed",
        )
        self.pull(tmp_path, manifest)

        pulled = load_baseline(tmp_path / "baselines", "tiny", "1")
        assert pulled == load_baseline(tmp_path / "computed", "tiny", "1")

    def evaluated(self, version, f1, fingerprint="set1"):
        from mlflow import MlflowClient

        client = MlflowClient()
        client.set_model_version_tag("tiny", version, "eval_f1", str(f1))
        client.set_model_version_tag("tiny", version, "eval_fingerprint", fingerprint)

    def champion(self):
        from mlflow import MlflowClient

        return str(MlflowClient().get_model_version_by_alias("tiny", "champion").version)

    def test_evaluation_is_stored_with_the_version(self, tmp_path, manifest, tf_serving):
        from mlflow import MlflowClient

        self.publish(tmp_path, manifest, b"v1 weights")
        dataset = evaluation_set(tmp_path, {"a.jpg": ["cat"]})

        model_registry.evaluate(coco_manifest(tmp_path), "tiny", "1", dataset)

        client = MlflowClient()
        version = client.get_model_version("tiny", "1")
        assert version.tags["eval_f1"] == "0.6667"
        assert version.tags["eval_dataset"] == "test_set"
        artifacts = {a.path for a in client.list_artifacts(version.run_id, "evaluation")}
        assert artifacts == {"evaluation/model_card.md", "evaluation/test_set.json"}

    def test_promotion_needs_an_evaluated_candidate(self, tmp_path, manifest):
        self.publish(tmp_path, manifest, b"v1 weights")
        self.publish(tmp_path, manifest, b"v2 weights")

        with pytest.raises(ValueError, match="not been evaluated"):
            model_registry.promote("tiny", "2", "champion")

        assert self.champion() == "1"

    def test_a_worse_candidate_is_refused_and_a_better_one_promoted(self, tmp_path, manifest):
        self.publish(tmp_path, manifest, b"v1 weights")
        self.publish(tmp_path, manifest, b"v2 weights")
        self.publish(tmp_path, manifest, b"v3 weights")
        self.evaluated("1", 0.80)
        self.evaluated("2", 0.70)
        self.evaluated("3", 0.85)

        with pytest.raises(ValueError, match=r"below the champion's 0\.800"):
            model_registry.promote("tiny", "2", "champion")
        model_registry.promote("tiny", "3", "champion")

        assert self.champion() == "3"

    def test_force_overrides_the_gate_and_says_so(self, tmp_path, manifest):
        from mlflow import MlflowClient

        self.publish(tmp_path, manifest, b"v1 weights")
        self.publish(tmp_path, manifest, b"v2 weights")

        model_registry.promote("tiny", "2", "champion", force=True)

        assert self.champion() == "2"
        reason = MlflowClient().get_model_version("tiny", "2").tags["promoted_without_gate"]
        assert "not been evaluated" in reason

    def test_candidate_is_served_next_to_the_champion_until_promoted(self, tmp_path, manifest):
        from mlflow import MlflowClient

        self.publish(tmp_path, manifest, b"v1 weights")
        self.publish(tmp_path, manifest, b"v2 weights")
        model_registry.promote("tiny", "2", "candidate")  # not gated

        assert self.pull(tmp_path, manifest) == {"tiny": "1"}  # the app keeps the champion
        assert read_lock(self.candidates(tmp_path)) == {"tiny": "2"}  # for shadow/canary
        config = (tmp_path / "model" / "model_config.config").read_text()
        assert "model_version_policy { specific { versions: 1 versions: 2 } }" in config
        assert (tmp_path / "model" / "tiny" / "2" / "saved_model.pb").exists()

        self.evaluated("1", 0.8)
        self.evaluated("2", 0.8)
        model_registry.promote("tiny", "candidate", "champion")  # the candidate alias's version

        assert "candidate" not in MlflowClient().get_registered_model("tiny").aliases
        assert self.pull(tmp_path, manifest) == {"tiny": "2"}
        assert read_lock(self.candidates(tmp_path)) == {}
        config = (tmp_path / "model" / "model_config.config").read_text()
        assert "model_version_policy { specific { versions: 2 } }" in config
