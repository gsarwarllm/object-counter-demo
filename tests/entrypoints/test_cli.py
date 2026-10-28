import json
import runpy
import sys
from pathlib import Path

import pytest

IMAGE = Path(__file__).parents[2] / "resources" / "images" / "cat.jpg"


def run_cli(monkeypatch, *args):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setattr(sys, "argv", ["counter.entrypoints.main", *args])
    runpy.run_module("counter.entrypoints.main", run_name="__main__")


def test_prints_the_count_response_as_json(monkeypatch, capsys):
    run_cli(monkeypatch, str(IMAGE), "0.5")

    assert json.loads(capsys.readouterr().out) == {
        "current_objects": [{"object_class": "cat", "count": 1}],
        "total_objects": [{"object_class": "cat", "count": 1}],
        "model": {"name": "ssd_mobilenet_v2", "version": None},
    }


def test_model_name_selects_the_model(monkeypatch, capsys):
    run_cli(monkeypatch, str(IMAGE), "0.5", "acme_shelf_detector")

    assert json.loads(capsys.readouterr().out)["model"]["name"] == "acme_shelf_detector"


def test_wrong_arguments_print_usage(monkeypatch):
    with pytest.raises(SystemExit, match="usage:"):
        run_cli(monkeypatch, str(IMAGE))


@pytest.mark.parametrize(
    ("threshold", "message"),
    [("5", r"threshold: must be between 0\.0 and 1\.0"), ("high", "threshold: must be a number")],
)
def test_invalid_threshold_is_rejected(monkeypatch, capsys, threshold, message):
    with pytest.raises(SystemExit, match=message):
        run_cli(monkeypatch, str(IMAGE), threshold)
    assert capsys.readouterr().out == ""
