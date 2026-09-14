-- Soft-archive sessions instead of deleting them: archived_at is NULL for a
-- visible session and set once it's archived, so every archived session
-- still opens by its direct URL and can be restored by clearing the column.
-- NULL sorts as "not archived" for every existing row -- no backfill needed.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS archived_at timestamptz;

-- Backs the default (unarchived, most-recent-first) session list query.
CREATE INDEX IF NOT EXISTS idx_sessions_created_at_unarchived
    ON sessions (created_at DESC) WHERE archived_at IS NULL;
