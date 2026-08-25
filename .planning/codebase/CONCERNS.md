# Codebase Concerns

<!-- refreshed: 2026-08-25 -->

**Analysis Date:** 2026-08-25

## Tech Debt

**Database Connection Pooling Bottleneck:**
- Issue: Connection pool configured with `max_size=5` (see `app/db.py:26`)
- Files: `backend/app/db.py`
- Impact: Under concurrent load, only 5 simultaneous database connections allowed. If multiple users send messages simultaneously, requests queue at the pool level. A single slow query blocks all pending requests.
- Fix approach: Increase `max_size` to 10-20 after load testing. Profile actual concurrent request patterns in production before adjusting.

**Synchronous Graph Execution Blocks Requests:**
- Issue: `graph.invoke()` in `send_message` endpoint is fully synchronous and blocks until completion (or approval interrupt)
- Files: `backend/app/api/sessions.py:87-94`, `backend/app/session_runner.py:90`
- Impact: A real Gemini call + tool execution can take 5-10 seconds, during which the entire request is blocked. Multiple concurrent users will exhaust server resources quickly. No async/background processing.
- Fix approach: Move graph execution to a background queue (Celery, RQ, or FastAPI background tasks). Store a "pending" job ID and let clients poll for results instead of blocking.

**No Explicit Pool Lifecycle Management:**
- Issue: `ConnectionPool` in `app/db.py` is created via `@lru_cache` and never explicitly closed
- Files: `backend/app/db.py:21-30`
- Impact: On app shutdown, database connections may not be cleanly closed, leading to hanging connections on the Postgres server. Pool leaks are silent until connection limits are hit.
- Fix approach: Add a shutdown handler to `FastAPI` that calls `pool.close()`. Example: `@app.on_event("shutdown") def shutdown(): get_db_pool().close()`

**Repository Layer Lacks Error Handling:**
- Issue: Every function in `repository.py` calls `conn.execute()` and returns the result directly with no try/except
- Files: `backend/app/repository.py` (all functions)
- Impact: Database errors (connection lost, disk full, constraint violations) are never caught. An `IntegrityError` or `OperationalError` propagates directly to the caller, often as a 500 with no logging context.
- Fix approach: Wrap each function in a try/except that logs the specific error and re-raises with a more specific exception type (e.g., `RepositoryError`). Callers can then decide whether to retry.

**Large Monolithic Graph Nodes File:**
- Issue: `nodes.py` is 374 lines and combines planning, tool calling, approval, decision logic in one file
- Files: `backend/app/graph/nodes.py`
- Impact: Hard to test individual node logic in isolation. Adding a new node type requires modifying this file. The file exceeds typical "one responsibility" guidelines.
- Fix approach: Extract related functions into submodules: `nodes/planner.py`, `nodes/tool_call.py`, `nodes/decide.py`, etc. Import and wire them in a top-level `nodes/__init__.py`.

---

## Scaling Limits

**No Pagination on list_sessions:**
- Problem: `list_sessions` returns all sessions (with `LIMIT 50` hard-coded) with no cursor or offset
- Files: `backend/app/repository.py:63-72`, `backend/app/api/sessions.py:48-50`
- Current capacity: 50 sessions returned per request
- Limit: When a deployment has 10,000+ sessions, the response grows to megabytes and query time degrades
- Scaling path: Add `offset` and `limit` parameters to `list_sessions`. Return a cursor and next/prev links. Update API schema and frontend to use pagination.

**Connection Pool Limited to 5 Concurrent Connections:**
- Problem: Postgres pool size is fixed at 5, no auto-scaling
- Files: `backend/app/db.py:26`
- Current capacity: 5 concurrent database operations
- Limit: 6+ simultaneous requests will queue at the pool. 50+ requests will timeout waiting for a connection.
- Scaling path: Monitor actual connection usage in production. Increase `max_size` to 15-20. For high-scale deployments, consider connection pooling via PgBouncer.

**Single Checkpoint Database for All Runs:**
- Problem: All graph state checkpoints (approval pause/resume) persist to the same Postgres table via `PostgresSaver`
- Files: `backend/app/db.py:41`, `langgraph-checkpoint-postgres` package
- Current capacity: LangGraph's checkpoint tables can handle thousands of runs before query performance degrades
- Limit: At 100,000+ concurrent paused sessions, checkpoint queries slow noticeably
- Scaling path: Monitor checkpoint table growth. Consider archiving old checkpoints to a separate cold-storage database. LangGraph v2 may offer partitioned checkpoint support.

---

## Known Issues

**Abandoned Sessions Never Timeout:**
- Symptoms: A session started by a user who closes their browser stays in "running" status forever. No automatic cleanup or timeout.
- Files: `backend/app/api/sessions.py`, `backend/app/graph/nodes.py`
- Trigger: User sends a message, session enters "running", then client crashes or network drops before graph finishes
- Workaround: Manually run `UPDATE sessions SET status='failed' WHERE updated_at < now() - interval '1 hour'` to mark stale sessions as failed
- Recommendation: Add an `updated_at` check in `start_session_run` and `resume_session_run` to fail sessions that haven't been touched in >30 minutes.

**Settings Environment Variable Leakage:**
- Symptoms: Tests using `pytest.monkeypatch.delenv` still read from the real OS environment if a matching env var is set
- Files: `backend/tests/conftest.py:14`, `backend/app/config.py`
- Root cause: pydantic-settings reads env vars BEFORE checking the `.env` file. A real OS env var overrides the test's explicit `Settings(_env_file=None)` instance.
- Impact: A test suite designed to use fake credentials can inadvertently use real secrets from the CI runner's environment
- Mitigation: ADR-017 implemented `SETTINGS_ENV_VAR_NAMES` + `monkeypatch.delenv` to close it (see `conftest.py:34-39`), but the root issue in pydantic-settings remains.

**Trace Detail Truncation:**
- Symptoms: Tool call results longer than 200 characters are silently truncated in the trace
- Files: `backend/app/graph/nodes.py:207`
- Impact: Long search results or note content is cut off, making trace review incomplete for debugging
- Recommendation: Store full result in a separate column or extend the 200-character limit to 1000+.

---

## Performance Bottlenecks

**LLM Provider Performance Not Monitored:**
- Problem: No metrics tracking how long Gemini/OpenRouter calls take, error rates, or latencies per provider
- Files: `backend/app/llm/base.py`, `backend/app/llm/gemini.py`, `backend/app/llm/openrouter.py`
- Impact: Can't tell if Gemini is slow, OpenRouter is timing out, or the failover is triggering frequently. Debugging slow runs is guesswork.
- Improvement path: Add timing instrumentation to `LLMProvider.generate()`. Log `provider`, `latency_ms`, `token_count`, and error type. Export to a metrics service (Datadog, Prometheus, etc.).

**Synchronous Tool Execution Blocks Decision Making:**
- Problem: `tool.run()` is always synchronous. If a tool makes an HTTP call that's slow, the entire decision pipeline stalls.
- Files: `backend/app/graph/nodes.py:175-200`
- Impact: A 10-second HTTP call in `web_search` blocks `decide_next` from running for 10 seconds, multiplied by 10 steps = 100 seconds wasted waiting for I/O.
- Improvement path: Refactor tool interface to support async. Use `asyncio` in the tool layer. Instrument slow tools to identify offenders.

**Frontend API Has No Retry Logic:**
- Problem: `fetch()` in `frontend/src/lib/api.ts` makes one attempt and throws on failure. No exponential backoff or retry.
- Files: `frontend/src/lib/api.ts:100-118`
- Impact: A single temporary network blip or server 5xx causes the user's request to fail. No resilience for transient failures.
- Improvement path: Add a retry utility with exponential backoff (e.g., `react-query`, `swr`, or custom). Retry 3 times on 5xx or network errors, then fail.

---

## Security Considerations

**Calculator Tool Resource Bounds Verified but Fragile:**
- Risk: The calculator tool's resource limits (`_MAX_EXPRESSION_LENGTH=500`, `_MAX_AST_DEPTH=50`, `_MAX_POW_RESULT_BITS=4096`) are correct in theory but depend on careful maintenance
- Files: `backend/app/tools/calculator.py:62-64`
- Current mitigation: ADR-020 documents live verification of each bound (10,000-char expression, `9**9**9`, 5,000-term chain). Bounds are enforced at parse/eval time.
- Recommendations: Add a test that runs deliberately pathological inputs to ensure bounds are actually hit. Document the bounds in a test comment so future maintainers know what to verify on any change.

**No Rate Limiting Configured:**
- Risk: Any client can hammer the API with unlimited requests (no DDoS protection beyond Postgres connection pool saturation)
- Files: `backend/requirements.txt:27` (slowapi imported but never used), `backend/app/main.py` (no RateLimiter middleware added)
- Current mitigation: `slowapi` is imported but not wired into the app. Render/Vercel deployment targets may have upstream rate limiting.
- Recommendations: Add slowapi middleware to `app/main.py` with a per-IP limit (e.g., 10 requests/minute for `/messages`, 100/minute for `/health`).

**Supabase Configuration Checked But Unused:**
- Risk: `supabase_url` and `supabase_secret_key` are validated at startup but never used. If a future feature tries to use them, stale keys could leak.
- Files: `backend/app/api/health.py:44`, `backend/app/config.py:54-55`
- Impact: Low immediate risk, but creates false sense of security. A developer might assume Supabase credentials are being used when they're not.
- Recommendations: Remove Supabase fields from Settings if unused. If Supabase is planned, document why config is checked but not used (e.g., "Phase 2 planning").

---

## Fragile Areas

**Approval Gate Node Relies on Interrupt Recovery:**
- Files: `backend/app/graph/nodes.py:99-135`
- Why fragile: LangGraph's `interrupt()` is called INSIDE a node. If the node re-executes after resume (which LangGraph does for checkpointing), the entire node function body runs again, including the `interrupt()` call. The comment documents that this is safe (interrupt short-circuits on resume), but it's fragile because it depends on LangGraph's exact implementation.
- Safe modification: Do not refactor this node without testing the approval pause/resume flow end-to-end. Add a test that verifies approval is not re-triggered on resume (see `test_graph_approval.py`).

**Observer Node ToolMessage Replacement Logic:**
- Files: `backend/app/graph/nodes.py:225-229`
- Why fragile: On a retry, the code filters out any prior `ToolMessage` with the same `tool_call_id` before appending a new one. This assumes message history is always valid JSON. If message serialization is changed, this filter could fail silently.
- Safe modification: Add validation that filtered messages round-trip through JSON serialization. Add a test that verifies message history stays valid after retries (see `test_graph_observe.py`).

**Concurrent Approval Decision Race:**
- Files: `backend/app/repository.py:164-181`, `backend/app/api/approvals.py:55-61`
- Why fragile: Two concurrent approve calls both check `status='pending'` and both execute the UPDATE. The WHERE clause prevents double-apply at the DB level, but the code checks `decided is None` AFTER the update to detect this. If two requests hit simultaneously, one gets a 409, but there's no mutual exclusion—just optimistic locking.
- Safe modification: Add an `IF` clause in the UPDATE to return before re-running the graph if the status is already 'approved'. Document this as intentional race condition handling, not a bug.

---

## Test Coverage Gaps

**Database-Backed Tests Require Live Postgres:**
- What's not tested: Full `repository` layer functionality is only tested against a real database
- Files: `backend/tests/conftest.py:65-82`, most `test_*.py` files with `db_pool` fixture
- Risk: Tests pass locally but fail on a CI runner without `DATABASE_URL` configured. Test suite skips silently instead of erroring loudly.
- Priority: Medium — integration tests ARE valuable, but CI should fail if the database is not available, not skip tests.
- Recommendations: Change pytest.skip to pytest.fail if `DATABASE_URL` is not set and DB-backed tests are present. Or, provide a Docker Compose setup so tests run against a real Postgres instance in CI.

**No Explicit E2E Tests for the Approval Modal:**
- What's not tested: The full round-trip of pausing on an approval, showing the modal, approving/rejecting, and resuming the graph
- Files: `frontend/src/components/ApprovalModal.test.tsx` (component tested in isolation), but no integration test that wires it through the session runner
- Risk: A frontend change could break the approval flow without being caught by unit tests
- Priority: High — this is a critical user-facing feature
- Recommendations: Add an E2E test using Playwright or Cypress that creates a session, triggers an approval, interacts with the modal, and verifies the session resumes.

**Calculator Tool Bounds Verified Manually, Not Automated:**
- What's not tested: The three resource bounds (`_MAX_EXPRESSION_LENGTH`, `_MAX_AST_DEPTH`, `_MAX_POW_RESULT_BITS`) are verified by hand (see ADR-020), not by tests
- Files: `backend/app/tools/calculator.py:54-61`, `backend/tests/test_tools_calculator.py`
- Risk: A future maintainer could increase a bound and accidentally break resource limits without noticing
- Priority: Medium
- Recommendations: Add explicit test cases for each boundary: `test_max_expression_length_exactly_500`, `test_max_expression_length_501_rejected`, etc. Use pytest.mark.parametrize to test each bound.

---

## Dependency Concerns

**LangGraph Version Pinning:**
- Risk: LangGraph is pinned to `1.2.11`. A future minor version (e.g., 1.3.0) could change checkpoint persistence or node re-execution behavior
- Files: `backend/requirements.txt:10`
- Impact: Approval pause/resume is built on LangGraph's checkpoint stability. A version upgrade could silently break this without errors.
- Mitigation: Version is explicitly pinned (ADR-004). Upgrade requires re-testing approval flow end-to-end.
- Recommendations: Add a note to any dependency upgrade checklist: "Approve pause/resume tested?" Document minimum LangGraph version in ARCHITECTURE.md.

**PostgreSQL Adapter Version:**
- Risk: `psycopg==3.3.4` and `langgraph-checkpoint-postgres==3.1.2` must stay compatible. Breaking changes in psycopg would cascade to LangGraph checkpointing.
- Files: `backend/requirements.txt:19-21`
- Mitigation: Both are version-pinned. LangGraph's checkpoint package is tested against specific psycopg versions.
- Recommendations: When upgrading either package, run the full integration test suite (especially `test_integration_session.py`) to verify checkpointing still works.

---

## Missing Critical Features

**No Session Timeout or Stale-Session Cleanup:**
- Problem: Sessions remain in "running" state indefinitely if a client crashes mid-execution
- Blocks: Accurate reporting of system load. A stale session that's never cleaned up wastes database space and confuses metrics.
- Recommendation: Implement a background job that marks sessions as "failed" if `updated_at < now() - 1 hour`. Or add a session TTL column and enforce in the API.

**No Metrics/Observability Export:**
- Problem: No Prometheus, Datadog, or CloudWatch integration. Can't see provider latency, tool error rates, or session duration distributions.
- Blocks: Production debugging and performance optimization. Slow deployments are invisible until users complain.
- Recommendation: Add logging via structlog (already imported in requirements.txt) and export to a metrics service. Start with: `provider_latency_ms`, `tool_error_count`, `session_duration_sec`.

**No Database Migration Runner:**
- Problem: Migrations in `backend/migrations/` are SQL files with no runner. `get_checkpointer()` calls `.setup()` (idempotent) but doesn't run `0001_initial_schema.sql` or `0002_session_created_status_and_default_task.sql`.
- Blocks: New deployments must manually apply migrations. No rollback mechanism.
- Recommendation: Add Alembic or Flyway integration to auto-run migrations on startup. Document in README.

---

*Concerns audit: 2026-08-25*
