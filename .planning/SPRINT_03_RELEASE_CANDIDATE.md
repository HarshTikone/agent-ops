# Sprint 03 — Release Candidate and Public Demo

> **Status: release verification in progress (2026-08-29).** The backend and
> initial frontend are public, production migrations are current, and the
> frontend redesign has passed local review. The redesigned build still needs
> redeployment plus final public CORS and approval/rejection acceptance evidence.

## Goal and constraints

Close the remaining backend/frontend release gaps, codify Render and Vercel
deployment, and verify both human-approval outcomes against public HTTPS URLs.
No new agent tools, account model, streaming, paid infrastructure, or custom
domain work is included.

## Delivery checklist

### Backend and persistence

- [x] Session listing embeds its pending action through one `LEFT JOIN`.
- [x] Forward migration `0004_release_hardening.sql` uses
  `DROP CONSTRAINT IF EXISTS` without modifying migration history.
- [x] The migration runner holds and always releases a PostgreSQL advisory lock.
- [x] Unexpected FastAPI errors are logged with traceback and returned as a
  generic JSON 500 response.
- [x] The unused application `port` setting is removed.
- [x] Focused regression tests cover joined retrieval, migration repeat/failure
  behavior, and exception sanitization.

### Frontend

- [x] Approval dialog uses a portal, initial focus, an inert application shell,
  focus trapping, focus restoration, and deliberate Escape no-op behavior.
- [x] Message, approval, and rejection states/errors are independent; mutations
  abort on unmount.
- [x] Enter submits, Shift+Enter inserts a newline, and the 8,000-character
  server limit is mirrored in the UI.
- [x] Readiness labels are human-readable.
- [x] Unknown routes and rendering failures have accessible recovery screens.
- [x] Production builds require `VITE_API_URL`; CI supplies a non-secret value.
- [x] The frontend README describes this application and its deployment.

### Release configuration and documentation

- [x] `render.yaml` defines a free Docker web service with `/health` liveness.
- [x] `frontend/vercel.json` defines the Vite build and SPA deep-link rewrite.
- [x] Root documentation describes migrations, deployment order, rollback,
  readiness, credentials, and cold starts.
- [x] ADR-022 through ADR-024 close the deferred decision-record gaps.
- [x] Pre-commit hooks are cross-platform and check only changed files.
- [x] Full local validation matrix passes after the final diff.
- [x] Independent review has no unresolved actionable P1/P2 findings.

### Public release evidence

- [x] Production migration run recorded (command, migration output, timestamp).
- [x] Render backend URL: <https://agent-ops-api-jcgc.onrender.com>.
- [x] Render `/health`: healthy on 2026-08-29.
- [x] Render `/health/ready`: ready on 2026-08-29.
- [x] Vercel frontend URL: <https://agent-ops-sage.vercel.app>.
- [ ] Exact-origin CORS and unauthenticated mutation checks recorded.
- [ ] Approval walkthrough recorded: task → pause → approve → trace → final.
- [ ] Rejection walkthrough recorded and persists after refresh.
- [ ] Screenshots added without exposing the operator key or provider secrets.

## Release procedure

1. Run the complete local validation matrix and review the diff.
2. Build `agent-ops-backend:release` from `backend/Dockerfile`.
3. Run `python -m scripts.migrate` from that image against the production
   `DATABASE_URL`; retain sanitized output as evidence.
4. Create/update Render from `render.yaml`, populate dashboard-only variables,
   and wait for `/health` to pass.
5. Create/update the Vercel project with Root Directory `frontend`, set
   `VITE_API_URL` to Render's HTTPS origin, and deploy.
6. Set Render `CORS_ORIGINS` to Vercel's exact production origin and redeploy.
7. Run health, readiness, security, approval, rejection, persistence, and trace
   acceptance checks. Record only non-secret results above.

## Rollback and operational notes

- Roll application code back by redeploying the previous known-good commit.
- Migrations are forward-only. Correct a production schema issue with a new
  migration; never alter an applied file.
- Render free services can cold-start after inactivity. Retry the first health
  request before diagnosing an outage.
- A paused Supabase project makes readiness `not_ready` while liveness stays
  healthy. Restore the database rather than restarting the API repeatedly.
- `degraded` is acceptable only when OpenRouter is intentionally absent;
  Gemini, Supabase configuration, and database reachability must be healthy.

## Verification log

| Gate | Result | Evidence |
|---|---|---|
| Frontend unit tests | Passed | 72 tests on 2026-08-28 |
| Frontend TypeScript | Passed | `tsc -b --pretty false` |
| Frontend ESLint | Passed | `eslint src vite.config.ts` |
| Focused backend tests | Passed | 5 tests (`test_migrate`, `test_lifecycle`) |
| Backend integration suite | Passed | 155 tests against isolated pgvector Postgres; live test deselected |
| Backend static checks | Passed | Ruff, Black, mypy (35 application files) |
| Migration repeat run | Passed | 0001–0004 applied once, then all four skipped |
| Backend release image | Passed | Built locally; UID 999; migration artifacts present |
| Container HTTP smoke | Passed | `/health` ok; dependency-free `/ready` reported `not_ready` |
| Frontend full matrix | Passed | ESLint, Prettier, strict TypeScript, 72 tests, Vite build |
| Missing production URL | Passed | Explicit empty `VITE_API_URL` makes Vite build exit 1 |
| Frontend redesign review | Passed | ESLint, Prettier, strict TypeScript, 80 tests, production Vite build, dark/light visual review on 2026-08-29 |
| Redesign reliability checks | Passed | Persistent local hide with Undo, keyboard/focus behavior, storage failure handling, and token-based status colors |
| Current backend regression | Passed | Ruff, mypy (36 source files), 116 passed, 39 database-dependent skipped, 1 live test deselected |
| Production migration | Passed | Release image applied 0003 and 0004 on 2026-08-29; immediate repeat skipped 0001–0004 |
| Public schema smoke | Passed | Public session detail and structured trace endpoint succeeded after migration |
| Redesigned frontend deployment and E2E | Pending | Commit/push, exact-origin CORS save, and public approval/rejection walkthrough remain |
