-- Recreate the session lifecycle constraint with an idempotent drop. This is
-- forward-only: already-applied migration files remain immutable.
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_status_check;
ALTER TABLE sessions ADD CONSTRAINT sessions_status_check
    CHECK (status IN ('created', 'running', 'awaiting_approval', 'done', 'failed'));
