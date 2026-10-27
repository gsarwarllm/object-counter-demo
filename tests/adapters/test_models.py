import json
from unittest.mock import Mock

import pytest

from counter.adapters.detector_factory import DetectorFactory
from counter.adapters.detector_registry import DetectorRegistry, ServedModel
from counter.adapters.model_manifest import (
    DEFAULT_MANIFEST,
    ModelSpec,
    candidates_lock,
    load_label_map,
    load_manifest,
    read_lock,
    write_lock,
)
from counter.adapters.object_detector import FakeObjectDetector, TFSObjectDetector


def write_manifest(tmp_path, models, default_model="a"):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"default_model": default_model, "models": models}))
    return path


def entry(name, serving="tfserving"):
    return {"name": name, "serving": serving, "label_map": "labels.json"}


def spec(name="a", serving="tfserving", label_map=None):
    return ModelSpec(name=name, serving=serving, label_map=label_map, registry_alias="champion")


class TestManifest:
    def test_repo_manifest_is_valid(self):
        manifest = load_manifest(DEFAULT_MANIFEST)

        assert manifest.default_model == "ssd_mobilenet_v2"
        assert manifest.names == ["ssd_mobilenet_v2", "acme_shelf_detector"]
        for model in manifest.models:
            assert load_label_map(model.label_map)[1] == "person"
            assert model.source_url.startswith("http://download.tensorflow.org/")

    def test_label_map_paths_are_relative_to_the_manifest(self, tmp_path):
        manifest = load_manifest(write_manifest(tmp_path, [entry("a")]))

        assert manifest.get("a").label_map == (tmp_path / "labels.json").resolve()
        assert manifest.get("a").registry_alias == "champion"

    @pytest.mark.parametrize(
        ("models", "default_model", "message"),
        [
            ([], "a", "no models"),
            ([entry("a"), entry("a")], "a", "duplicate"),
            ([entry("a")], "b", "default_model 'b'"),
        ],
    )
    def test_invalid_manifests_are_rejected(self, tmp_path, models, default_model, message):
        with pytest.raises(ValueError, match=message):
            load_manifest(write_manifest(tmp_path, models, default_model))

    def test_candidates_lock_lives_next_to_the_lock(self, tmp_path):
        assert candidates_lock(tmp_path / "models.lock.json") == tmp_path / "candidates.lock.json"

    def test_lock_round_trip(self, tmp_path):
        lock = tmp_path / "nested" / "models.lock.json"
        write_lock({"a": "3"}, lock)

        assert read_lock(lock) == {"a": "3"}
        assert read_lock(tmp_path / "missing.json") == {}


class TestDetectorFactory:
    def test_builds_tf_serving_detector_with_labels_and_version(self):
        coco = load_manifest(DEFAULT_MANIFEST).get("ssd_mobilenet_v2")

        detector = DetectorFactory(tfs_host="tfs", tfs_port=9000).create(coco, "4")

        assert isinstance(detector, TFSObjectDetector)
        assert detector.url == "http://tfs:9000/v1/models/ssd_mobilenet_v2/versions/4:predict"
        assert detector.classes_dict[17] == "cat"

    def test_force_serving_overrides_the_manifest(self):
        detector = DetectorFactory(force_serving="fake").create(spec(serving="tfserving"), None)

        assert isinstance(detector, FakeObjectDetector)

    def test_unknown_serving_type_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown serving type 'onnx' for model 'a'"):
            DetectorFactory().create(spec(serving="onnx"), None)


class TestDetectorRegistry:
    def test_get_returns_named_or_default_model(self):
        a, b = ServedModel("a", "1", Mock()), ServedModel("b", "2", Mock())
        registry = DetectorRegistry([a, b], default_model="b")

        assert registry.get("a") is a
        assert registry.get(None) is b
        assert registry.names == ["a", "b"]
        with pytest.raises(KeyError):
            registry.get("c")

    def test_default_must_be_a_served_model(self):
        with pytest.raises(ValueError, match="Default model 'x'"):
            DetectorRegistry([ServedModel("a", None, Mock())], default_model="x")

    def test_from_manifest_requires_versions_when_asked(self, tmp_path):
        manifest = load_manifest(write_manifest(tmp_path, [entry("a"), entry("b")]))
        factory = DetectorFactory(force_serving="fake")

        with pytest.raises(ValueError, match=r"No pulled version for models \['b'\]"):
            DetectorRegistry.from_manifest(manifest, factory, {"a": "1"}, require_versions=True)

        registry = DetectorRegistry.from_manifest(manifest, factory, {}, require_versions=False)
        assert registry.get("b").version is None

    def test_from_manifest_adds_candidate_versions(self, tmp_path):
        manifest = load_manifest(write_manifest(tmp_path, [entry("a"), entry("b")]))
        (tmp_path / "labels.json").write_text('[{"id": 1, "display_name": "cat"}]')
        factory = DetectorFactory()

        registry = DetectorRegistry.from_manifest(
            manifest,
            factory,
            {"a": "1", "b": "1"},
            require_versions=True,
            candidate_versions={"a": "2"},
        )

        assert registry.get("a").candidate.version == "2"
        assert registry.get("a").candidate.detector.url.endswith("/v1/models/a/versions/2:predict")
        assert registry.get("b").candidate is None
