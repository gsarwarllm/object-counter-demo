import logging

import pytest

from counter.logging_config import LOG_FORMAT, _AppLogHandler, configure_logging


@pytest.fixture(autouse=True)
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
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
