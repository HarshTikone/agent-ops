# Next Sprint — Reliability Foundation

> **Status: completed 2026-08-27.** All four work packages and their
> automated acceptance gates are implemented. The opt-in live-provider smoke
> workflow remains intentionally manual.

## Sprint goal

Make Agent Ops safe to harden and deploy by fixing persistence consistency,
making trace data trustworthy, correcting approval execution semantics, and
establishing deterministic, secret-free CI.

This sprint deliberately adds no new agent tools or user-facing features.

## Duration and capacity

- Duration: 5 focused development days
- Target capacity: 20–25 engineering hours
- Delivery strategy: four small vertical work packages, each independently
  reviewed and merged

## Success criteria

The sprint succeeds when all of the following are true:

- A failure during result persistence cannot leave contradictory session,
  approval, message, and trace state.
- Every trace event has a stable sequence, structured severity, and optional
  provider attribution.
- A pending action is marked `executed` only at the tool-attempt boundary.
- Default CI runs without Gemini, Tavily, OpenRouter, or Supabase secrets.
- CI uses an isolated PostgreSQL service with migrations applied.
- Backend lint, format, type checks, and tests pass; frontend lint, format,
  strict type checks, tests, and production build pass.
- Architecture and ADR documentation accurately describe the remaining
  checkpoint/application-database atomicity limitation.

## Work package 1 — Transactional persistence

### Objective

Make each application-side graph result apply atomically.

### Tasks

- Add repository functions that can operate on an existing database connection
  instead of opening and committing a separate connection for every write.
- Wrap `_apply_result` application-table writes in one transaction.
- Persist trace events, pending-action creation, assistant messages, and session
  status changes through that transaction.
- Change status-only updates so they do not erase an existing `final_answer`.
- Treat a graph invocation that returns neither an interrupt nor a terminal
  status as an explicit failure instead of silently retaining `running`.
- Add failure-injection tests at each write boundary.

### Acceptance criteria

- If any write in `_apply_result` fails, none of that result's application-table
  writes are committed.
- No test can produce a pending action while its session remains `running`.
- No status-only update clears a previously stored final answer.
- Existing start, pause, reject, approve, retry, failure, and completion tests
  continue to pass.

### Estimate

6–8 hours

## Work package 2 — Trustworthy structured traces

### Objective

Replace positional trace inference and free-text severity parsing with durable,
explicit trace metadata.

### Tasks

- Add a forward-only migration containing:
  - `trace_events.sequence` scoped to a session
  - `trace_events.level` constrained to `info`, `success`, `warning`, or `error`
  - a unique index on `(session_id, sequence)`
  - an index on `sessions(created_at DESC)`
- Define a typed trace-event shape in graph state.
- Assign sequence, level, and provider at the event creation site.
- Replace `len(list_trace_events(...))` diffing with sequence-based persistence.
- Return the new fields from API schemas and TypeScript interfaces.
- Render trace tone from `level`, keeping detail parsing only as a temporary
  fallback for rows created before the migration.
- Add tests for pause/resume continuity, duplicate prevention, provider
  attribution, and trace ordering.

### Acceptance criteria

- Deleting or duplicating an old trace row cannot cause new events to be skipped.
- Replaying persistence for the same graph state is idempotent.
- Provider failover is visible in persisted trace data.
- Frontend trace styling does not depend on English substrings for new rows.

### Estimate

5–6 hours

## Work package 3 — Correct approval execution semantics

### Objective

Ensure the approval audit trail distinguishes a decision from an actual tool
attempt.

### Tasks

- Remove the pre-resume `executed` transition from the approval endpoint.
- Move the transition to the graph/tool boundary immediately before an approved
  irreversible tool is invoked.
- Keep approval decision updates concurrency-safe.
- Define behavior when checkpoint loading fails, tool execution fails, or result
  persistence fails after a tool attempt.
- Add tests for all three failure positions.
- Append an ADR documenting the state semantics and unavoidable ambiguity when
  an external side effect succeeds but the following database write fails.

### Acceptance criteria

- A checkpoint or graph-start failure leaves the action `approved`, never
  `executed`.
- Once the tool call begins, the action records that attempt even when the tool
  returns a classified failure.
- Two concurrent decisions cannot execute the same action twice.
- Session failure recovery does not falsify the approval audit trail.

### Estimate

3–4 hours

## Work package 4 — Deterministic CI and strict checks

### Objective

Make the main CI workflow reproducible on branches and forks without live
credentials.

### Tasks

- Add a PostgreSQL service container to the backend CI job.
- Apply migrations before backend tests.
- Ensure default tests use scripted/mock LLM and HTTP providers.
- Mark live Gemini/Tavily/Supabase tests as `live` and exclude them by default.
- Add a manually triggered live-integration workflow or documented local command.
- Add mypy and configure typed-definition, implicit-optional, and unused-ignore
  checks.
- Enable TypeScript `strict` and `noUncheckedIndexedAccess`.
- Fix real typing errors rather than widening interfaces to `Any`.
- Confirm CI works with all provider and Supabase secrets absent.

### Acceptance criteria

- A fork can run the full default CI workflow without repository secrets.
- Default CI makes no external LLM or Tavily calls.
- Each CI run gets an isolated migrated database.
- Ruff, Black, mypy, pytest, ESLint, Prettier, Vitest, TypeScript, and the Vite
  production build all pass.

### Estimate

6–7 hours

## Suggested daily sequence

### Day 1

- Implement connection-aware repository operations.
- Make `_apply_result` transactional.
- Add rollback/failure-injection tests.

### Day 2

- Add the trace migration and typed trace structure.
- Implement sequence-based, idempotent persistence.
- Add backend trace tests.

### Day 3

- Update API and frontend trace models/rendering.
- Correct approval execution semantics.
- Add approval failure-position tests and ADR.

### Day 4

- Move CI to an isolated PostgreSQL service.
- Separate default and live tests.
- Add mypy and strict TypeScript configuration.

### Day 5

- Resolve remaining type/lint/test failures.
- Run the full local and CI-equivalent validation matrix.
- Perform a final diff review and update architecture/status documentation.

## Test matrix

### Required on every pull request

- Backend: Ruff, Black check, mypy, secret-free pytest
- Frontend: ESLint, Prettier check, Vitest, TypeScript build, Vite build
- PostgreSQL: fresh service container plus all migrations

### Required before sprint completion

- Full approval flow: pause → approve → execute → done
- Rejection flow: pause → reject → replan/fail as designed
- Failure injection before, during, and after `_apply_result`
- Checkpoint-loading failure before tool execution
- Tool failure after execution begins
- Duplicate/replayed trace persistence
- One opt-in live Gemini/Tavily/Supabase smoke run

## Explicitly deferred

- API authentication and rate limiting
- FastAPI lifespan and shared HTTP-client lifecycle
- Live database readiness checks
- Approval-dialog accessibility polish
- Error boundary and not-found UI
- Render/Vercel deployment
- New tools, streaming, multi-user accounts, and semantic memory

These become the following sprint once persistence and CI provide a safe base.

## Risks and controls

- **Checkpoint and application writes cannot share one transaction.** Document
  this boundary honestly and make application-table persistence idempotent.
- **Schema changes touch backend and frontend contracts.** Merge the migration,
  API model, frontend model, and compatibility fallback together.
- **Strict typing can expand unexpectedly.** Time-box cosmetic typing cleanup;
  prioritize boundary types and correctness errors.
- **Live tests can consume quota.** Keep them opt-in and never part of ordinary
  pull-request CI.

## Definition of done

- All acceptance criteria above are demonstrated by automated tests.
- The CI workflow passes from a clean checkout with no external-service secrets.
- Migrations run successfully against a fresh PostgreSQL database and an
  already-migrated database.
- No real finding remains from the sprint-end code review.
- `PROJECT.md`, `REQUIREMENTS.md`, `ARCHITECTURE.md`, and append-only ADRs reflect
  the implemented behavior.
- The main branch is left deployable to a development environment, with no
  partially completed schema or frontend-contract change.
