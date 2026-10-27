import logging
import os

LOG_FORMAT = "%(asctime)s %(levelname)s [%(process)d] %(name)s: %(message)s"


class _AppLogHandler(logging.StreamHandler):
    """Marks the handler this module installs, so configuring twice doesn't add a second one."""


def configure_logging(level: str | None = None) -> None:
    """One format for every logger (app, Flask, Werkzeug, psycopg_pool, ...) on stderr.

    Called by every entrypoint, including create_app(), so it also applies under gunicorn,
    which never runs the `__main__` block. The level comes from LOG_LEVEL (default INFO).
    """
    level_name = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    if level_name not in logging.getLevelNamesMapping():
        raise ValueError(f"Unknown LOG_LEVEL {level_name!r}; expected e.g. DEBUG, INFO, WARNING")
    root = logging.getLogger()
    if not any(isinstance(handler, _AppLogHandler) for handler in root.handlers):
        handler = _AppLogHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)
    root.setLevel(level_name)
