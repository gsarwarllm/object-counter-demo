"""gunicorn settings for the Docker image (`gunicorn -c counter/entrypoints/gunicorn_conf.py`)."""

import os
import shutil
from pathlib import Path
from typing import Any

# All interfaces: inside the container, port 5000 is only reachable through the published port.
bind = "0.0.0.0:5000"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
# One access line per request on stdout, with its duration and request ID.
accesslog = "-"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms request_id=%({x-request-id}o)s'


def on_starting(server: Any) -> None:
    """Prometheus multiprocess mode needs an empty directory when the server starts."""
    directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if directory:
        shutil.rmtree(directory, ignore_errors=True)
        Path(directory).mkdir(parents=True)


def child_exit(server: Any, worker: Any) -> None:
    """Drops the metric files of a worker that exited, so /metrics doesn't count it twice."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess

        multiprocess.mark_process_dead(worker.pid)
