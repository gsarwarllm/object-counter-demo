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

EXPOSE 5000
# --access-logfile -: one line per request on stdout (gunicorn logs none by default)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--access-logfile", "-", \
     "counter.entrypoints.webapp:create_app()"]
