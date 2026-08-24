-- Reworks sessions' lifecycle to match ARCHITECTURE.md's documented flow:
-- POST /sessions creates an empty session shell first; the graph only
-- starts running once the first POST /sessions/{id}/messages call arrives
-- and supplies the task. 0001 didn't have a state for "created but nothing
-- has run yet" and required `task` up front -- fixed here via ALTER rather
-- than rewriting 0001, since migrations are forward-only just like the
-- ADR log is append-only.
ALTER TABLE sessions ALTER COLUMN task SET DEFAULT '';

ALTER TABLE sessions DROP CONSTRAINT sessions_status_check;
ALTER TABLE sessions ADD CONSTRAINT sessions_status_check
    CHECK (status IN ('created', 'running', 'awaiting_approval', 'done', 'failed'));
ALTER TABLE sessions ALTER COLUMN status SET DEFAULT 'created';
