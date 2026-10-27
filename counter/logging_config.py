import json
import logging
import os

from flask import g, has_request_context

LOG_FORMAT = "%(asctime)s %(levelname)s [%(process)d] [%(request_id)s] %(name)s: %(message)s"
LOG_FORMATS = ("text", "json")


class _AppLogHandler(logging.StreamHandler):
    """Marks the handler this module installs, so configuring twice doesn't add a second one."""


class RequestIdFilter(logging.Filter):
    """Adds request_id to every record: the current request's X-Request-ID, or "-" outside one."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = g.get("request_id", "-") if has_request_context() else "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for log shippers (LOG_FORMAT=json)."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "pid": record.process,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def configure_logging(level: str | None = None, log_format: str | None = None) -> None:
    """One format for every logger (app, Flask, Werkzeug, psycopg_pool, ...) on stderr.

    Called by every entrypoint, including create_app(), so it also applies under gunicorn,
    which never runs the `__main__` block. The level comes from LOG_LEVEL (default INFO), the
    format from LOG_FORMAT (text, the default, or json).
    """
    level_name = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    if level_name not in logging.getLevelNamesMapping():
        raise ValueError(f"Unknown LOG_LEVEL {level_name!r}; expected e.g. DEBUG, INFO, WARNING")
    format_name = (log_format or os.environ.get("LOG_FORMAT", "text")).lower()
    if format_name not in LOG_FORMATS:
        raise ValueError(f"Unknown LOG_FORMAT {format_name!r}; expected one of {list(LOG_FORMATS)}")
    root = logging.getLogger()
    handler = next((h for h in root.handlers if isinstance(h, _AppLogHandler)), None)
    if handler is None:
        handler = _AppLogHandler()
        handler.addFilter(RequestIdFilter())
        root.addHandler(handler)
    handler.setFormatter(
        JsonFormatter() if format_name == "json" else logging.Formatter(LOG_FORMAT)
    )
    root.setLevel(level_name)
