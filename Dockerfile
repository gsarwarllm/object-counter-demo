FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY counter ./counter
COPY models ./models
COPY docs/openapi.yaml ./docs/openapi.yaml

RUN useradd --create-home appuser
USER appuser

# Workers share their Prometheus metrics through this directory (see counter/metrics.py).
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus

EXPOSE 5000
# Bind address, workers, access log and metrics clean-up: counter/entrypoints/gunicorn_conf.py
CMD ["gunicorn", "-c", "counter/entrypoints/gunicorn_conf.py", \
     "counter.entrypoints.webapp:create_app()"]
