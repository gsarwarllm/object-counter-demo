CREATE TABLE IF NOT EXISTS prediction_logs (
    id         BIGSERIAL    PRIMARY KEY,
    logged_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    model      VARCHAR(255) NOT NULL,
    version    VARCHAR(64)  NOT NULL,
    scores     REAL[]       NOT NULL,
    classes    TEXT[]       NOT NULL
);

CREATE INDEX IF NOT EXISTS prediction_logs_model_version_time
    ON prediction_logs (model, version, logged_at);
