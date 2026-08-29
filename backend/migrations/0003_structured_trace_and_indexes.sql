-- Durable, idempotent trace ordering and structured presentation metadata.
ALTER TABLE trace_events ADD COLUMN sequence bigint;
ALTER TABLE trace_events ADD COLUMN level text NOT NULL DEFAULT 'info';

WITH numbered AS (
    SELECT id, row_number() OVER (PARTITION BY session_id ORDER BY id) AS sequence
    FROM trace_events
)
UPDATE trace_events
SET sequence = numbered.sequence
FROM numbered
WHERE trace_events.id = numbered.id;

ALTER TABLE trace_events ALTER COLUMN sequence SET NOT NULL;
ALTER TABLE trace_events ADD CONSTRAINT trace_events_level_check
    CHECK (level IN ('info', 'success', 'warning', 'error'));
CREATE UNIQUE INDEX trace_events_session_sequence_idx
    ON trace_events (session_id, sequence);
CREATE INDEX sessions_created_at_desc_idx ON sessions (created_at DESC);
