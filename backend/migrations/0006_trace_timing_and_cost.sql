-- Adds latency, token, and cost columns to trace_events (P3 of the
-- 2026-09-11 remediation).
--
-- All five are nullable, and that is not laziness: the sessions that ran
-- before this migration still need to render, and a node that doesn't (or
-- can't -- see approval_gate_node) capture timing must not be forced to
-- claim a fabricated value. `—` in the UI, not `0ms` or `$0.00`.
ALTER TABLE trace_events
    ADD COLUMN started_at  timestamptz,
    ADD COLUMN duration_ms integer,
    ADD COLUMN tokens_in   integer,
    ADD COLUMN tokens_out  integer,
    ADD COLUMN cost_usd    numeric(12,6);
