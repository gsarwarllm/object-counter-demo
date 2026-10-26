FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY counter ./counter

RUN useradd --create-home appuser
USER appuser

EXPOSE 5000
# -O skips the debug-image drawing in the domain actions.
CMD ["python", "-O", "-m", "gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", \
     "counter.entrypoints.webapp:create_app()"]
