import json

import pytest

from counter.monitoring.evaluation import (
    DEFAULT_EVALUATION_SET,
    EvaluationSet,
    evaluate,
    gate,
    load_evaluation_set,
    model_card,
)


def labelled(labels):
    return EvaluationSet("test_set", None, {k: frozenset(v) for k, v in labels.items()}, "abc")


def test_sample_set_has_its_images_and_a_stable_fingerprint():
    first, second = load_evaluation_set(), load_evaluation_set()

    assert [image.name for image in first.images] == ["boy.jpg", "cat.jpg", "food.jpg"]
    assert first.labels["cat.jpg"] >= {"cat"}
    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 12


def test_fingerprint_changes_with_the_labels(tmp_path):
    data = json.loads(DEFAULT_EVALUATION_SET.read_text())
    data["images_dir"] = str(DEFAULT_EVALUATION_SET.parent / data["images_dir"])
    data["labels"]["cat.jpg"] = ["cat"]
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(data))

    assert load_evaluation_set(changed).fingerprint != load_evaluation_set().fingerprint


def test_missing_images_are_reported(tmp_path):
    path = tmp_path / "set.json"
    path.write_text(json.dumps({"name": "x", "images_dir": ".", "labels": {"gone.jpg": ["cat"]}}))

    with pytest.raises(ValueError, match=r"gone\.jpg"):
        load_evaluation_set(path)


def test_micro_and_per_class_scores():
    evaluation_set = labelled({"a.jpg": ["cat"], "b.jpg": ["cat", "person"]})

    result = evaluate(evaluation_set, {"a.jpg": {"cat", "dog"}, "b.jpg": {"cat", "dog"}})

    # cat: 2 true positives; dog: 2 false positives; person: 1 missed
    assert (result.precision, result.recall, result.f1) == (0.5, 0.6667, 0.5714)
    assert result.per_class["cat"].f1 == 1.0
    assert result.per_class["dog"].precision == 0.0
    assert (result.per_class["person"].recall, result.per_class["person"].support) == (0.0, 1)
    assert (result.dataset, result.images) == ("test_set", 2)


def test_perfect_and_empty_detections():
    evaluation_set = labelled({"a.jpg": ["cat"]})

    assert evaluate(evaluation_set, {"a.jpg": {"cat"}}).f1 == 1.0
    assert evaluate(evaluation_set, {}).f1 == 0.0


@pytest.mark.parametrize(
    ("candidate", "champion", "allowed", "reason"),
    [
        ((None, None), (0.8, "set1"), False, "not been evaluated"),
        ((0.7, "set1"), (None, None), True, "no evaluated champion"),
        ((0.7, "set1"), (0.8, "set2"), False, "same evaluation set"),
        ((0.7, "set1"), (None, "set1"), False, "same evaluation set"),
        ((0.7, "set1"), (0.8, "set1"), False, "below the champion's 0.800"),
        ((0.79, "set1"), (0.8, "set1"), True, "tolerance"),
        ((0.9, "set1"), (0.8, "set1"), True, "candidate F1 0.900 vs champion 0.800"),
    ],
)
def test_gate(candidate, champion, allowed, reason):
    decision = gate(*candidate, *champion, tolerance=0.02)

    assert decision.allowed is allowed
    assert reason in decision.reason


def test_model_card_lists_the_metrics_per_class():
    result = evaluate(labelled({"a.jpg": ["cat"]}), {"a.jpg": {"cat"}})

    card = model_card("m", "3", "A detector.", "https://example.invalid/m.tar.gz", result)

    assert card.startswith("# Model card: m v3")
    assert "| F1 | 1.000 |" in card
    assert "| cat | 1 | 1.00 | 1.00 | 1.00 |" in card
    assert "`test_set` (1 images, fingerprint `abc`)" in card
