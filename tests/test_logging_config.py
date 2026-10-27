import json
import logging

import pytest
from flask import Flask, g

from counter.logging_config import LOG_FORMAT, _AppLogHandler, configure_logging


@pytest.fixture(autouse=True)
def restore_root_logger():
    """Each test starts without the app handler (an earlier create_app() may have installed one,
    bound to a stream pytest has since closed) and the root logger is restored afterwards."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    root.handlers[:] = [h for h in handlers if not isinstance(h, _AppLogHandler)]
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def app_handlers():
    return [h for h in logging.getLogger().handlers if isinstance(h, _AppLogHandler)]


def test_defaults_to_info(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    configure_logging()

    assert logging.getLogger().level == logging.INFO


def test_log_level_env_sets_the_level(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    configure_logging()

    assert logging.getLogger().level == logging.DEBUG


def test_unknown_log_level_is_rejected(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "LOUD")

    with pytest.raises(ValueError, match="Unknown LOG_LEVEL 'LOUD'"):
        configure_logging()


def test_configuring_twice_installs_one_handler():
    configure_logging("INFO")
    configure_logging("WARNING")

    assert len(app_handlers()) == 1
    assert app_handlers()[0].formatter._fmt == LOG_FORMAT
    assert logging.getLogger().level == logging.WARNING


def test_text_lines_carry_the_request_id(capsys):
    configure_logging("INFO", "text")
    app = Flask(__name__)

    with app.test_request_context():
        g.request_id = "req-42"
        logging.getLogger("test").info("inside")
    logging.getLogger("test").info("outside")

    lines = capsys.readouterr().err.splitlines()
    assert lines[-2].endswith("[req-42] test: inside")
    assert lines[-1].endswith("[-] test: outside")


def test_json_format_writes_one_object_per_line(capsys):
    configure_logging("INFO", "json")

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logging.getLogger("test").exception("failed")

    entry = json.loads(capsys.readouterr().err.splitlines()[-1])
    assert entry["level"] == "ERROR"
    assert entry["logger"] == "test"
    assert entry["message"] == "failed"
    assert entry["request_id"] == "-"
    assert "RuntimeError: boom" in entry["exception"]


def test_unknown_log_format_is_rejected(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "xml")

    with pytest.raises(ValueError, match="Unknown LOG_FORMAT 'xml'"):
        configure_logging()
