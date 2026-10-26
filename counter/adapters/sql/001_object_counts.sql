CREATE TABLE IF NOT EXISTS object_counts (
    object_class VARCHAR(255) PRIMARY KEY,
    count        BIGINT       NOT NULL DEFAULT 0 CHECK (count >= 0),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
