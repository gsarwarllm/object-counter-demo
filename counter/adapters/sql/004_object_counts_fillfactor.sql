-- object_counts is a few rows updated on every request. Free space in each page (fillfactor 80)
-- lets PostgreSQL rewrite a row on the same page without touching the primary key index
-- (a HOT update), so the table and index don't bloat. Checked first: ALTER TABLE takes a lock.
DO $$
BEGIN
    IF NOT coalesce(
        (SELECT reloptions @> ARRAY['fillfactor=80'] FROM pg_class
         WHERE oid = 'object_counts'::regclass),
        false
    ) THEN
        ALTER TABLE object_counts SET (fillfactor = 80);
    END IF;
END $$;
