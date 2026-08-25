# Requirements — Agent Ops (Days 5-7)

Source: `PROJECT.md`'s Active requirements, `reviews/day-4-fix-prompt.md`'s 6 remaining phases
(the precise decomposition of this scope — Days 1-4 and Phase 1 are already `Validated` in
PROJECT.md, not repeated here), and `.planning/research/SUMMARY.md`'s findings. This is a
brownfield subsequent-milestone project: scope was already fixed by the review-remediation
plan before this requirements pass, so categories map 1:1 onto the fix-prompt's phases rather
than an open feature menu.

## v1 Requirements

### Persistence & Trace Durability (fix-prompt Phase 2)

- [ ] **PERSIST-01**: `_apply_result`'s writes (pending-action creation, session status update, trace event) happen inside a single database transaction — a failure mid-sequence leaves no partial state (e.g. a `pending` action on a session still marked `running`) (H2)
- [ ] **PERSIST-02**: Trace events are diffed against a monotonic per-session sequence number, not `len()` of a full row fetch — a deleted or out-of-order row can never silently drop or duplicate trace events (H3)
- [ ] **PERSIST-03**: Every trace event records which LLM provider produced it (`trace_events.provider` is actually written, not always `NULL`), so a failover event is visible in the trace, not just in logs (H4)
- [ ] **PERSIST-04**: Every trace event carries a structured `level` (`info`/`success`/`warning`/`error`) set at the write site, not inferred later from substring-matching free text (H4, feeds M12)
- [ ] **PERSIST-05**: `update_session_status` never silently wipes a stored `final_answer` when called for a status-only update (M3)
- [ ] **PERSIST-06**: The database connection pool is closed on app shutdown via a FastAPI `lifespan` hook, and a `check=` callback detects and discards dead connections (e.g. after a Supabase idle-drop) before handing them out (M1)
- [ ] **PERSIST-07**: `sessions (created_at DESC)` has an index, and fetching a session's pending action is a single `LEFT JOIN`, not an N+1 query (L13, L14)
- [ ] **PERSIST-08**: The migration runner takes a Postgres advisory lock so two concurrent runs can't race, and uses `DROP CONSTRAINT IF EXISTS` for idempotent re-runs (L12)
- [ ] **PERSIST-09**: The persistence fix explicitly documents (ADR) that the LangGraph checkpoint commit and the app-table transaction are still two separate commits, not one atomic unit — a scoped, accepted residual gap, not silently implied to be fully atomic (research: PITFALLS.md)

### Type Safety (fix-prompt Phase 3)

- [ ] **TYPES-01**: `mypy` runs in backend CI with `disallow_untyped_defs`, `warn_unused_ignores`, `no_implicit_optional` enabled, and the build fails if it reports an error (H6)
- [ ] **TYPES-02**: The `Tool` Protocol's declared signature actually matches what the three tool implementations do — not widened to `**kwargs: Any` to make mypy pass without fixing the real mismatch (H6, pitfall guard)
- [ ] **TYPES-03**: A session deleted between two statements returns a 404, not a 500 from an unhandled `None` (H6)
- [ ] **TYPES-04**: TypeScript `strict` and `noUncheckedIndexedAccess` are enabled in both `tsconfig.app.json` and `tsconfig.node.json`, and the frontend build fails on a type error (H5)
- [ ] **TYPES-05**: `LLMProvider` is `@runtime_checkable`, and `FailoverProvider` has a real `name` attribute instead of relying on a `getattr` fallback (L19)
- [ ] **TYPES-06**: Message content, reject reasons, and list-endpoint `limit` parameters are server-side validated (non-empty, length-bounded), not only enforced client-side (M5)

### Tool-Adapter Reliability (fix-prompt Phase 4)

- [ ] **TOOLS-01**: A database error from the notes tool (not just `OperationalError`) is caught and classified transient-vs-permanent, never escapes as a raw exception (M6)
- [ ] **TOOLS-02**: A network error from the web-search tool beyond timeouts (e.g. `ReadError`, `RemoteProtocolError`) is caught and classified, never escapes as a raw exception (M7)
- [ ] **TOOLS-03**: The web-search tool shares one `httpx.Client` with a proper open/close lifecycle instead of leaking a new client on every invocation (M2)
- [ ] **TOOLS-04**: `tool_call_node` has a final catch-all backstop that converts any uncaught tool exception into a permanent step failure and logs it with a traceback — no tool can ever crash a whole run (defense in depth)

### Security & Readiness (fix-prompt Phase 5)

- [ ] **SEC-01**: Every mutating endpoint (`POST /sessions/*`, `POST /approvals/*`) requires a valid shared-secret API key; an unauthenticated request is rejected (H1)
- [ ] **SEC-02**: The frontend sends the API key on every mutating request — this ships in the same phase/commit boundary as SEC-01, not deferred, so the deployed app never briefly breaks itself (H1, research pitfall)
- [ ] **SEC-03**: Mutating endpoints are rate-limited per-IP via `slowapi`; requests past the threshold get a 429 (H1)
- [ ] **SEC-04**: `/health/ready` performs a real timed `SELECT 1` against the database — a paused or unreachable database reports `not_ready`, not `ready` (H7)
- [ ] **SEC-05**: The readiness DB check has an explicit short timeout, so a slow-resuming database degrades the readiness check itself rather than piling up requests against the connection pool (H7, research pitfall)
- [ ] **SEC-06**: `/health/ready`'s existing three-way semantics (`ready`/`degraded`/`not_ready`) are preserved — a missing OpenRouter key still reports `degraded`, not `not_ready`, and the frontend can still distinguish "misconfigured" from "unreachable" (H7)
- [ ] **SEC-07**: Backend CI runs against a Postgres service container (with migrations applied), not the shared live Supabase project, so concurrent branch runs never interfere with each other's test data (H8)
- [ ] **SEC-08**: Live-LLM-calling tests are opt-in only (a pytest marker), not run on every PR (H8)
- [ ] **SEC-09**: The full backend test suite passes with zero secrets set in the environment — confirming CI is safe to run on a fork (H8)
- [ ] **SEC-10**: The backend Docker image runs as a non-root user, is a genuine multi-stage build (builder stage's `build-essential` never ships in the runtime image), includes `migrations/` and `scripts/` so `migrate.py` is runnable from the image, and has a `HEALTHCHECK` against `/health` — liveness, never `/health/ready` (M9, research: don't point platform health checks at readiness)
- [ ] **SEC-11**: `tenacity` and `structlog` are either actually used or removed from dependencies (M10)

### Frontend Accessibility & Polish (fix-prompt Phase 6)

- [ ] **FE-01**: The approval modal traps focus inside itself while open — Tab/Shift+Tab never reaches the page behind the overlay (M11)
- [ ] **FE-02**: The approval modal sets initial focus on open and marks the background `inert` (or equivalent) so a screen-reader user can't interact with anything behind it (M11)
- [ ] **FE-03**: The approval modal has a documented, deliberate Escape-key behavior (either mirrors Reject or is an explicit no-op) — not left as an accidental gap, since dismissing an approval prompt by accident is a real hazard (M11)
- [ ] **FE-04**: An automated test (RTL) asserts focus moves into the approval dialog on open, Tab cycles within it, and Escape does the documented thing (M11, research differentiator: tested not just declared)
- [ ] **FE-05**: The trace viewer's color/tone comes from the structured `level` field (PERSIST-04), with substring-matching kept only as a fallback for pre-migration rows (M12)
- [ ] **FE-06**: A production build with no `VITE_API_URL` set fails loudly at load time instead of silently pointing at `localhost` (L2)
- [ ] **FE-07**: Unmounting mid-action never sets state on a dead component or surfaces a spurious error (`AbortError` is ignored, matching the existing mount-effect pattern) (L3)
- [ ] **FE-08**: The chat panel never suppresses a real send failure just because a pending approval also exists; Enter submits (Shift+Enter for a newline); message length is capped client-side to match the server-side bound (L4-L7)
- [ ] **FE-09**: The approval modal shows a submitting state on Reject, not only on Approve (L4-L7)
- [ ] **FE-10**: The backend-status display maps check keys to human-readable labels, not raw snake_case identifiers (L4-L7)
- [ ] **FE-11**: An unknown route shows a real not-found page, and a React error boundary wraps the app's routes (L4-L7)
- [ ] **FE-12**: `frontend/README.md` reflects this project, not the untouched Vite scaffold template (L8)

### Documentation Truth-Up (fix-prompt Phase 7)

- [ ] **DOCS-01**: Root `README.md`'s status line and endpoint list reflect the actual current system (not "Day 1 of a 7-day build"), without yet doing the full Day 5 problem-first rewrite (L9)
- [ ] **DOCS-02**: `ARCHITECTURE.md` and `.env.example` files use one consistent name per environment variable (`SUPABASE_SECRET_KEY`, not a stale `SUPABASE_SERVICE_KEY` reference; one home per default value) (L10, L11)
- [ ] **DOCS-03**: `main.py` registers the Phase 2 `lifespan` hook and a global exception handler that logs with a traceback and returns a clean 500 body; the unused `settings.port` field is either wired up or removed (L1)
- [ ] **DOCS-04**: Pre-commit hooks use pre-commit's native `entry`/`args`/working-directory support instead of a fragile `bash -c 'cd … && …'` shell-out, and only lint changed files (L17)
- [ ] **DOCS-05**: `conftest.py` documents that `db_pool` is session-scoped against a shared database and that SEC-07's CI service container is what makes that safe (L15)
- [ ] **DOCS-06**: A new append-only ADR exists for each of: the C1 provider-construction fix, the C2/C3 limit-semantics changes, the H1 auth choice, the H7 readiness change, the H3/H4 trace-durability changes, and the M12 supersession of ADR-019 (Phase 7)
- [ ] **DOCS-07**: `ARCHITECTURE.md` gains a "Day 4.5 amendments" section summarizing what changed and why, without rewriting its existing sections (Phase 7)

### Deployment (Day 6)

- [ ] **DEPLOY-01**: The backend is deployed to Render's free tier as a Docker container, reachable over HTTPS, with production environment variables (API keys, database URL, CORS origin, shared-secret API key) configured and verified live
- [ ] **DEPLOY-02**: The frontend is deployed to Vercel's free tier as a static build, with `VITE_API_URL` pointed at the live Render backend and CORS configured with the exact scheme-qualified origin
- [ ] **DEPLOY-03**: Render's platform health-check configuration points at `/health` (liveness), not `/health/ready`, so a temporarily-down dependency degrades readiness reporting without triggering a restart loop
- [ ] **DEPLOY-04**: The deployed system's free-tier cold-start behavior (Render spin-down, Supabase 7-day pause) is documented honestly in the README rather than silently assumed away

### Final Review (Day 7)

- [ ] **SHIP-01**: A full code review (reviewer subagent → `REVIEW.md`) runs against the complete Days 5-6 diff, and every real finding is fixed before this is called done, per this project's established self-review convention
- [ ] **SHIP-02**: A live end-to-end walkthrough confirms the demo-critical path works against the deployed system: send a task, see it pause for approval, approve it, see the trace and final answer — not just against local dev

## v2 (Deferred)

- Full user accounts / Supabase Auth / OAuth-SSO login — a shared-secret API key is the chosen v1 mechanism; revisit only if a second real operator is ever added
- Real-time push/streaming trace updates (websockets/SSE) — polling is sufficient at demo scale; revisit only if poll latency becomes visibly slow in a live demo

## Out of Scope

- Redis-backed distributed rate limiting — solves a multi-instance consistency problem this single-Render-instance project doesn't have (`slowapi` in-memory storage is the correct choice, not a shortcut)
- Cryptographically signed / tamper-proof / blockchain-anchored audit log — solves an adversarial-DBA threat model this portfolio demo doesn't have; the append-only `ADR.md`/forward-only-migrations convention is the right rigor level
- Full RBAC / per-action permission scoping — one operator, one credential; no scenario exercises per-role permissions
- MFA / passkeys / hardware-key auth — doesn't reduce risk on a single shared secret with one legitimate holder
- Horizontal scaling / multi-instance deployment — a hard scope boundary from `MASTER_PROMPT.md`, not an oversight
- Any paid infrastructure tier, for any service — a hard constraint from `MASTER_PROMPT.md`

## Traceability

_Filled in during roadmap creation — maps each REQ-ID above to the phase(s) that deliver it._
