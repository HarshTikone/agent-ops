-- Adds the `degraded` terminal status (P1 of the 2026-09-11 remediation).
--
-- A degraded session ran its plan to completion but no provider returned an
-- answer that passed `app/answer_quality.validate_answer` — it carries the
-- deterministic fallback built from tool results instead of a model summary.
-- It is answer-bearing like `done`, not incomplete like `failed`, and the
-- separate status is what keeps a fallback from being counted as a clean
-- success by the UI or by `scripts/audit_sessions.py`.
--
-- Forward-only, matching 0004: drop-if-exists then recreate, so this applies
-- cleanly whether or not 0004 has run.
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_status_check;
ALTER TABLE sessions ADD CONSTRAINT sessions_status_check
    CHECK (status IN ('created', 'running', 'awaiting_approval', 'done', 'degraded', 'failed'));
