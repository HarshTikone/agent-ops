-- A session's list title, decoupled from `task` (WP5, ADR-036): `task` is
-- overwritten on every follow-up turn by repo.restart_session (ADR-033), so
-- a session's card in the list would otherwise silently retitle itself to
-- whatever the most recent message said. `title` is set once, on a
-- session's first message, and never touched again.
ALTER TABLE sessions ADD COLUMN title text;

-- Backfill: the first user message's content for every existing session,
-- falling back to the current `task` for the rare session with no messages
-- yet (a 'created' row that was never sent a first message).
UPDATE sessions s
SET title = COALESCE(
    (
        SELECT content FROM messages
        WHERE session_id = s.id AND role = 'user'
        ORDER BY created_at
        LIMIT 1
    ),
    s.task
)
WHERE title IS NULL;
