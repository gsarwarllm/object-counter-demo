from counter.monitoring.baseline import Baseline, baseline_path, load_baseline, save_baseline
from counter.monitoring.drift import distributions
from tests.monitoring.helpers import confident_cats


def test_saved_baseline_loads_back(tmp_path):
    baseline = Baseline(
        "m", "3", "2026-10-27T00:00:00+00:00", "test images", distributions(confident_cats(4))
    )

    path = save_baseline(baseline, tmp_path)

    assert path == baseline_path(tmp_path, "m", "3") == tmp_path / "m" / "3.json"
    assert load_baseline(tmp_path, "m", "3") == baseline


def test_baselines_written_before_input_statistics_still_load(tmp_path):
    """X2 baselines have no input-feature fields; they load with empty input distributions."""
    path = tmp_path / "m" / "1.json"
    path.parent.mkdir()
    path.write_text(
        '{"model": "m", "version": "1", "created_at": "t", "source": "s", "distributions": '
        '{"images": 2, "scores": [0,0,0,0,0,0,0,0,0,2], "detections": [0,2,0,0,0,0,0], '
        '"classes": {"cat": 2}}}'
    )

    loaded = load_baseline(tmp_path, "m", "1")

    assert loaded.distributions.images == 2
    assert loaded.distributions.input_images == 0


def test_missing_baseline_is_none(tmp_path):
    assert load_baseline(tmp_path, "m", "3") is None
