-- Retention deletes rows by age. Rows are appended in time order, so a BRIN index (one small
-- summary per block range, kilobytes instead of a B-tree's megabytes) finds old rows cheaply.
CREATE INDEX IF NOT EXISTS prediction_logs_logged_at_brin
    ON prediction_logs USING brin (logged_at);
