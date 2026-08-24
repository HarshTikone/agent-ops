-- Day 3 schema: sessions, the user-facing message log, the trace log, the
-- approval state machine, and per-session notes storage.
--
-- LangGraph's own checkpoint/checkpoint_blobs/checkpoint_writes tables (the
-- low-level graph-state persistence behind the approval pause/resume flow,
-- ADR-014) are NOT created here -- they're owned and versioned by the
-- langgraph-checkpoint-postgres package itself via PostgresSaver.setup(),
-- which app/db.py calls at startup. Hand-writing SQL for tables we don't
-- control the shape of would drift the moment that package changes them.
--
-- pgvector is enabled per the original stack plan (master prompt 2.2,
-- ARCHITECTURE.md's Data section) but session_memory below has no embedding
-- column yet -- nothing writes one this day. See ADR-014.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task text NOT NULL,
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'awaiting_approval', 'done', 'failed')),
    final_answer text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_session_id_idx ON messages (session_id);

CREATE TABLE trace_events (
    id bigserial PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    node text NOT NULL,
    detail text NOT NULL,
    provider text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX trace_events_session_id_idx ON trace_events (session_id);

CREATE TABLE pending_actions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    tool_name text NOT NULL,
    tool_args jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'executed')),
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz
);
CREATE INDEX pending_actions_session_id_idx ON pending_actions (session_id);
CREATE INDEX pending_actions_pending_idx ON pending_actions (session_id) WHERE status = 'pending';

CREATE TABLE session_memory (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    key text NOT NULL,
    content text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, key)
);
