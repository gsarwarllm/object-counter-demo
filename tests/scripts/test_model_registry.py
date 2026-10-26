import io
import json
import tarfile

import pytest

from counter.adapters.model_manifest import load_manifest, read_lock
from scripts import model_registry


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
    config = model_registry.tf_serving_config({"b_model": "7", "a_model": "2"})

    assert config.index('name: "a_model"') < config.index('name: "b_model"')
    assert 'base_path: "/models/a_model"' in config
    assert "model_version_policy { specific { versions: 2 } }" in config
    assert "model_version_policy { specific { versions: 7 } }" in config


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
        model_registry.pull(manifest, tmp_path / "model", tmp_path / "model" / "models.lock.json")
        return read_lock(tmp_path / "model" / "models.lock.json")

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

        model_registry.promote("tiny", "2", "champion")

        assert self.pull(tmp_path, manifest) == {"tiny": "2"}
        assert (tmp_path / "model" / "tiny" / "2" / "saved_model.pb").read_bytes() == b"v2 weights"

    def test_promote_rejects_unknown_versions(self, tmp_path, manifest):
        from mlflow.exceptions import MlflowException

        self.publish(tmp_path, manifest, b"v1 weights")

        with pytest.raises(MlflowException):
            model_registry.promote("tiny", "9", "champion")
