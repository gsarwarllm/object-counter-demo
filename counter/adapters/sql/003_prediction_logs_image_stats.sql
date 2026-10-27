-- Input image statistics (X4). Nullable: rows logged before this migration have none.
ALTER TABLE prediction_logs ADD COLUMN IF NOT EXISTS width       INTEGER;
ALTER TABLE prediction_logs ADD COLUMN IF NOT EXISTS height      INTEGER;
ALTER TABLE prediction_logs ADD COLUMN IF NOT EXISTS color_mode  VARCHAR(16);
ALTER TABLE prediction_logs ADD COLUMN IF NOT EXISTS brightness  REAL;
ALTER TABLE prediction_logs ADD COLUMN IF NOT EXISTS contrast    REAL;
