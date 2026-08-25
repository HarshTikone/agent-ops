# Remediation prompt — Agent Ops, all Day 1–4 review findings

Paste everything below the line into Claude Code from the repo root (`D:\agent-ops`).

---

You are working in the `agent-ops` repo at tag `day-4-complete` (`d4df774`). A full code review of Days 1–4 produced the findings below. Fix **all of them**, including the nits. Work through the phases in order — later phases depend on earlier ones.

## Ground rules

- **Verify, don't assume.** This repo's standard (ADR-010, ADR-013, ADR-017) is that behavioral claims are checked against the installed package or a real run, not inferred from docs or from the shape of an error message. Hold that line: if a fix depends on how `psycopg`, `langgraph`, `langchain-*`, or `pydantic-settings` actually behaves, prove it in a scratch script before writing the fix, and say in the ADR what you ran.
- **`ADR.md` is append-only.** Never edit an existing ADR. Corrections go in a new ADR that names the one it supersedes (this is what ADR-008 and ADR-014 do).
- **`ARCHITECTURE.md` is amend-only.** Add a "Day 4.5 amendments" section; do not rewrite sections 1–9.
- **Migrations are forward-only.** New numbered file, never edit `0001`/`0002`.
- **Every fix needs a test that fails before it and passes after.** ADR-007 is the standard here: after writing each regression test, reintroduce the bug and confirm the test actually fails by name. A test that passes against the reintroduced bug is not a test — it is decoration. Do this for at least C1, C2, C3, C4, H3, and H4.
- **Commit per phase** with the repo's existing conventional-commit style. Do not squash phases together.
- Keep `ruff check .`, `black --check .`, `npm run lint`, `npm run format:check` green at every commit.
- Do not add features. Do not start Day 5 scope (rate limiting, metrics endpoint, README rewrite) except where a finding below explicitly calls for it.

---

## Phase 1 — Critical correctness (blocking)

### C1. A Gemini-only deploy cannot serve a single request

`app/dependencies.py:get_llm_provider()` eagerly constructs `OpenRouterProvider`, and `ChatOpenAI` raises `openai.OpenAIError: Missing credentials` at construction time when `api_key` is empty. Reproduce first:

```python
# GEMINI_API_KEY set, OPENROUTER_API_KEY unset
from app.dependencies import get_llm_provider
get_llm_provider()   # OpenAIError
```

This contradicts ADR-009 and `health.py`'s docstring, which both define `degraded` as "can serve every request, just no failover safety net."

Fix: when `openrouter_api_key` **or** `openrouter_model` is empty, return the bare `GeminiProvider` instead of wrapping it in a `FailoverProvider`. Log once at startup that failover is disabled. Do **not** paper over it by defaulting the key to a placeholder string.

Also give `config.py` a validator that rejects the half-configured state at startup: `openrouter_api_key` set with `openrouter_model` empty (or vice versa) should fail fast with a clear message rather than 500 on the first request.

Tests: `get_llm_provider` with Gemini-only settings returns a usable provider; with both set returns a `FailoverProvider`; the half-configured combination raises at `Settings` construction.

### C2. `calculator` is an unbounded DoS on LLM-controlled input

`9**9**9` never returns — it pins a CPU and holds a threadpool worker. `expression` comes straight from the planner LLM. The AST allow-list closes code execution but does nothing about resource exhaustion.

Fix in `app/tools/calculator.py`:

- Cap `len(expression)` (something like 500 chars) before `ast.parse`.
- Cap AST depth during the walk (something like 50) — this also fixes **M8**, where a deeply nested expression raises `RecursionError`, which is not in the `except (TypeError, OverflowError, ValueError)` tuple and escapes as a non-`ToolError`.
- Before applying `ast.Pow`, reject exponents and operands whose magnitude would blow up (e.g. `abs(exponent) > 100`, or check the estimated bit length of the result). Keep `2 ** 10` working — the existing test asserts it.
- Every rejection is a permanent `ToolError`, consistent with the rest of the module.

Tests: `9**9**9`, `2**(10**10)`, a 10 000-character expression, and a 500-deep nesting each raise a permanent `ToolError` **quickly** (assert with a wall-clock bound — this is a timing bug, so a test that only asserts the exception type would pass against a version that takes an hour to raise it).

### C3. A fully successful `MAX_TOOL_CALLS`-step plan is reported as `failed`

In `decide_next_node`, the `tool_calls_made >= MAX_TOOL_CALLS` check sits above the success/finalize branch, so a plan that completes on exactly its tenth tool call gets `give_up` / `status="failed"` / "Stopped after 10 tool calls without finishing the task." Reproduce by calling `decide_next_node` directly with a 10-step plan, `step_index=9`, `tool_calls_made=10`, `last_failure=None`.

Fix: the cap must pre-empt **continuing**, not **finishing**. Move it below the success branch, or gate it so it only fires when there is more work to do. Update `limits.py`'s docstring to state that precedence explicitly.

Tests: exactly `MAX_TOOL_CALLS` successful steps → `finalize`; `MAX_TOOL_CALLS` reached with steps remaining → `give_up`.

### C4. Any exception during a run wedges the session permanently

`sessions.send_message` and `approvals._decide` call `start_session_run` / `resume_session_run` with no `try`/`except`, after the row has already been flipped to `running`. On any raise the session stays `running` forever; the 409 guard then blocks every retry.

Fix: wrap both call sites. On exception —

- `update_session_status(..., status="failed", final_answer=<short message>)`,
- write a `trace_events` row recording the crash so the failure is visible in the trace viewer (not just in logs),
- `logger.exception(...)` with the traceback,
- return `HTTPException(502)` with a real `detail`.

For the approval path specifically: move `mark_pending_action_executed` so a failed resume doesn't strand the action at `approved` on a session stuck at `awaiting_approval`. Decide and document whether "executed" means "attempted" or "completed" — the current comment says attempted, the current placement implements completed.

Tests: inject a provider that raises; assert the session lands on `failed`, a trace row exists, and the endpoint returns 502 rather than a bare 500. Same for a resume that raises.

**Commit:** `fix(backend): resolve four Day 1-4 critical correctness defects`

---

## Phase 2 — Data integrity and the persistence layer

### H2. Make `_apply_result` transactional

It currently issues 2–4 independent autocommit statements. A failure between `create_pending_action` and `update_session_status` leaves a `pending` action on a session still marked `running` — the frontend only fetches `pending_action` when `status == 'awaiting_approval'`, so the modal never appears and the run is unrecoverable.

Give `repository.py` a way to run several statements on one connection in one transaction (a context manager, or accept an optional `conn`), and make each `_apply_result` outcome atomic. Test by forcing a failure mid-sequence and asserting no partial state survives.

### H3. Replace the count-based trace diff

`already_persisted = len(repo.list_trace_events(pool, session_id))` reads every column of every row to take a length, then slices the in-state trace by it. Any divergence between row count and trace length silently drops or duplicates events forever.

Fix: give `trace_events` a monotonic per-session sequence number (new migration) and diff on that, or write trace rows inside the Phase-2 transaction. Either way stop using `len()` of a full `SELECT` as an offset. Add a regression test that deletes a trace row mid-run and asserts nothing is silently skipped.

### H4. Actually write `trace_events.provider`

The column exists, `TraceEventResponse` exposes it, and `TraceViewer.tsx` renders `via {provider}` — but `session_runner.py:50` never passes `provider=`, so it is always `NULL` and that UI branch is dead code. Which provider answered is the observable payoff of ADR-002's failover.

Fix: add `provider: str | None` to the `TraceEvent` TypedDict in `graph/state.py`, set it from `response.provider` in `planner_node` and `finalize_node`, and pass it through `_persist_new_trace_events`. Test end-to-end that a graph run driven by a provider named `"openrouter"` produces a trace row with `provider = 'openrouter'`.

While in `state.py`, add a `level` field (`"info" | "success" | "warning" | "error"`) set at each trace site. **M12** depends on it: `TraceViewer.toneFor` currently substring-matches free-text `detail`, so a planner line whose tool args contain the word "retry" renders amber.

### M3. `update_session_status` silently nulls `final_answer`

`final_answer` is always in the `SET` clause with a `None` default, so a status-only update wipes any stored answer. Make it a sentinel-guarded optional update, or split into two functions.

### M1. Pool lifecycle

Add a FastAPI `lifespan` that closes the pool on shutdown. Replace `ConnectionPool(..., open=True)` with the non-deprecated form (**verify** against the installed `psycopg_pool` 3.3.1 which form that is — don't guess from the deprecation warning text). Add a `check=` callback so a Supabase idle-drop doesn't hand out a dead connection.

### L13, L14. `list_sessions` query shape

Add an index on `sessions (created_at DESC)` in the new migration. Collapse the `session_with_pending_action` N+1 into a single `LEFT JOIN` against `pending_actions WHERE status = 'pending'`.

### L12. Migration hygiene

Use `DROP CONSTRAINT IF EXISTS` in the new migration's pattern, and make `migrate.py` take a Postgres advisory lock so two concurrent runners can't race. Note in its docstring that it must be run with `backend/` as CWD.

**Commit:** `fix(backend): make session persistence transactional and the trace log durable`

---

## Phase 3 — Type safety and the contracts nothing enforces

### H6. Add mypy, fix its five findings

Add `mypy` to `requirements-dev.txt`, configure it in `pyproject.toml` (strict enough to be worth having: `disallow_untyped_defs`, `warn_unused_ignores`, `no_implicit_optional`), and add a step to the backend CI job.

Fix what it finds:

- `app/tools/registry.py:23–25` — all three tools structurally violate the `Tool` Protocol. `Tool.run` is declared `run(self, **kwargs: Any) -> str`, the implementations are keyword-specific. Make the Protocol honest: either declare `run` to match what the implementations do, or have the registry go through a typed dispatch that mypy can actually check. The file claims to enforce "the uniform tool-adapter interface" — make that claim true. Do not silence it with `# type: ignore`.
- `app/api/sessions.py:89`, `app/api/approvals.py:73` — `repo.get_session()` returns `dict | None` and is passed straight into `session_with_pending_action`, which subscripts it. A session deleted between two statements gives a `TypeError` → 500. Handle the `None` (404), don't cast it away.

### H5. Turn on TypeScript `strict`

Add `"strict": true` and `"noUncheckedIndexedAccess": true` to **both** `tsconfig.app.json` and `tsconfig.node.json`. This has been verified to produce exactly one error, in `src/lib/api.test.ts:75` (destructuring a possibly-`undefined` array element) — fix that properly, not with `!`.

### L19. Protocol details

Mark `LLMProvider` `@runtime_checkable`, and give `FailoverProvider` a `name` (e.g. `"failover"`) so `failover.py`'s `getattr(provider, "name", ...)` fallbacks aren't load-bearing.

### M5. Server-side input validation

- `CreateMessageRequest.content`: `min_length=1`, a sane `max_length`, strip whitespace. Right now an empty task is only blocked client-side by `ChatPanel`.
- `RejectRequest.reason`: `max_length`.
- `GET /sessions`: a validated `limit` query parameter (default 50, bounded) instead of a hardcoded constant.
- `GET /sessions/{id}/trace`: bound it too.

**Commit:** `chore(backend,frontend): enforce the type contracts the code already claims`

---

## Phase 4 — Error handling and resource leaks at the boundaries

### M6. `notes_store` catches too narrowly

Only `psycopg.OperationalError` is caught; a `DataError`/`ProgrammingError` escapes as a raw exception through `tool_call_node`, which only catches `ToolError`. That breaks ARCHITECTURE §6's "every tool failure is caught at the adapter boundary, not hoped for at the call site." Catch `psycopg.Error` as the base and classify: `OperationalError` → transient, everything else → permanent.

### M7. `web_search` catches too narrowly

`httpx.ReadError`, `RemoteProtocolError`, `TooManyRedirects` escape. Catch `httpx.HTTPError` as the base and classify.

### M2. `WebSearchTool` leaks an `httpx.Client`

A client is created per instance and never closed, and `build_tool_registry` runs on **every** `.invoke()`. Either share one module-level client with a proper lifecycle, or make the tool a context manager the registry closes. Add a test that a run doesn't leak clients.

### Defense in depth for `tool_call_node`

Given M6/M7, add a final `except Exception` in `tool_call_node` that logs with traceback and converts to a permanent step failure — so no tool can ever crash a whole run, whatever it raises. Keep the specific `ToolError` branch above it; this is a backstop, not a replacement.

**Commit:** `fix(backend): close the tool-adapter exception and resource boundaries`

---

## Phase 5 — Security, readiness, and CI

### H1. Authentication and rate limiting

`GET /sessions` returns every session to anyone who can reach the URL, and `POST /approvals/{id}/approve` lets any caller execute the irreversible action the whole human-in-the-loop design exists to gate. An unauthenticated approve endpoint defeats ADR-015/016 entirely.

ARCHITECTURE.md schedules rate limiting for Day 5 and deploy for Day 6, so this must be decided before the deploy, not after. Implement the minimum that makes the gate mean something:

- A shared-secret API key header, or Supabase Auth if you'd rather bring Day 4's optional item forward. Either is fine; pick one and write an ADR for the choice and what it gives up.
- Wire up `slowapi` (already a declared dependency, currently unimported) with a per-IP limit on the mutating endpoints.
- Review the `allow_credentials=True` CORS setting against whichever auth scheme you pick.

Tests: unauthenticated calls to the mutating endpoints are rejected; the rate limiter returns 429 past the threshold.

### H7. Make `/health/ready` actually dial its dependencies

It currently checks only that config strings are non-empty. README documents that Supabase free projects pause after 7 days — against a paused project this endpoint reports `ready`, which is exactly the failure its own docstring says it exists to catch.

Add a real `SELECT 1` through the pool with a short timeout; a failure downgrades to `not_ready`. Keep the existing three-way semantics from ADR-009 (missing OpenRouter → `degraded`, not `not_ready`) and keep the config checks as separate fields so the frontend can still tell "misconfigured" from "unreachable" — which means `ReadinessChecks` in `api.ts` gains a field and `BackendStatus.tsx` needs updating in step. Write an ADR.

### H8. Make CI runnable on forks and not dependent on one shared database

- Add a `postgres` service container with `pgvector` and run `scripts/migrate.py` against it for the DB-backed tests, instead of pointing them at the shared live Supabase project (where concurrent branch runs interfere — `test_list_sessions_endpoint_returns_most_recent_first` reads globally-visible rows).
- Put the live-LLM tests behind an opt-in pytest marker (`-m live`) that runs on `main` or on manual dispatch, not on every PR.
- Confirm the whole suite passes on a runner with **no** secrets at all — that is the fork case.
- Add the mypy step from Phase 3 and a coverage threshold (`@vitest/coverage-v8` and a `test:coverage` script already exist and are unused).
- Add `dependabot.yml` for pip, npm, and GitHub Actions.

### M9. Backend Dockerfile

- Add a non-root `USER`.
- Multi-stage: build wheels in a builder stage, so `build-essential` doesn't ship in the runtime image. The `AS base` label currently promises a structure that isn't there.
- `COPY migrations ./migrations` and `COPY scripts ./scripts` — `migrate.py` currently cannot be run from the image, which will bite on the Render deploy.
- Add a `HEALTHCHECK` hitting `/health`.
- Drop the hardcoded `EXPOSE 8000` or make it consistent with the `$PORT`-driven CMD (**L21**).

### M10. Remove unused dependencies

`tenacity` and `structlog` are declared and never imported. Either use `structlog` (ARCHITECTURE promises structured logging and `main.py` uses `logging.basicConfig`) or drop both from `requirements.txt`. `slowapi` gets used by H1 above.

### L16. nginx

Add gzip, long-lived cache headers for hashed assets with `no-cache` for `index.html`, and basic security headers (`X-Content-Type-Options`, `Referrer-Policy`, a CSP). Run nginx as non-root.

**Commit:** `feat(backend,ci): authenticate the approval gate, make readiness real, isolate CI`

---

## Phase 6 — Frontend polish and accessibility

### M11. Make `ApprovalModal` a real modal

It declares `role="dialog" aria-modal="true"` with no focus trap, no initial focus, no Escape handler, and no `inert`/`aria-hidden` on the background — so keyboard and screen-reader users can tab straight into the page behind the overlay, on the one dialog in the app that gates an irreversible action.

Either use the native `<dialog>` element with `showModal()`, or implement focus trapping + Escape + background `inert` by hand. Add RTL tests: focus moves into the dialog on open, Tab cycles within it, Escape triggers the same path as Reject (or is explicitly a no-op — decide and document, since dismissing an approval prompt by accident is a real hazard).

### M12. Trace tone from a structured field

With Phase 2's `level` column in place, replace `TraceViewer.toneFor`'s substring matching with a direct lookup. Keep the text heuristic only as a fallback for rows written before the migration. Supersede ADR-019's trace-tone decision with a new ADR.

### L2. Production API URL

`VITE_API_URL ?? 'http://localhost:8000'` silently points a production build at localhost. Throw at module load when `import.meta.env.PROD` and the variable is unset.

### L3. `runAction` abort handling

`SessionPage.runAction` calls `refetch()` with no `AbortSignal` and doesn't special-case `AbortError`, so unmounting mid-action sets state on a dead component and surfaces a spurious error. Thread a controller through and ignore `AbortError`, matching what the mount effect already does.

### L4, L5, L6, L7. The rest

- `ChatPanel`: stop suppressing `actionError` when a `pending_action` exists (`error={load.session.pending_action ? null : actionError}` hides real send failures); submit on Enter (Shift+Enter for newline); add a `maxLength` matching Phase 3's server-side bound.
- `ApprovalModal`: show a submitting label on Reject, not just Approve.
- `BackendStatus`: map check keys to human labels ("Gemini API key", not "gemini_api_key_set missing").
- `App.tsx`: add a `*` catch-all route with a real not-found page, and a React error boundary around the routes.

### L8. Delete the scaffold README

`frontend/README.md` is the untouched Vite template, referring to Oxlint (this project uses ESLint), the React Compiler, and `plugin-react-swc`. Replace it with a short real one, or delete it and let the root README cover the frontend.

**Commit:** `fix(frontend): make the approval dialog accessible and the trace tone structured`

---

## Phase 7 — Documentation truth-up

- **L9.** Root `README.md` still says "**Status: Day 1 of a 7-day build**" and documents none of `GET /sessions`, `GET /sessions/{id}`, or the frontend routes. Update the status line and the endpoint list. This is *not* the Day 5 rewrite (lead-with-the-problem) — just stop being wrong.
- **L10.** `ARCHITECTURE.md` §6 names `SUPABASE_SERVICE_KEY`; the variable is `SUPABASE_SECRET_KEY` everywhere else.
- **L11.** `GEMINI_MODEL`'s default is duplicated in `config.py` and `.env.example`, and `VITE_API_URL` appears in both the root and `frontend/` `.env.example`. Pick one home for each and have the other point at it.
- **L1.** `main.py`: add the `lifespan` from Phase 2, a global exception handler that logs with traceback and returns a clean 500 body, and either use `settings.port` or remove the field (it is currently read from env and never used). Note that `logging.basicConfig` at import time is a no-op when logging is already configured, and fix accordingly.
- **L17.** Pre-commit hooks shell out via `bash -c 'cd … && …'`, fragile on the Windows box this repo is developed on. Use pre-commit's `entry` + `args` + working-directory support instead, and pass filenames so hooks don't lint the whole tree on every commit.
- **L18.** `pyproject.toml` sets `asyncio_mode = "auto"` with no async tests — remove it, or add the async tests that justify it.
- **L20.** `observe_node` dedupes prior `ToolMessage`s by `tool_call_id`; add a defensive check (or a comment with a test) covering two planner steps sharing an id.
- **L15.** Document in `conftest.py` that `db_pool` is session-scoped against a shared database, and that Phase 5's CI service container is what makes that safe.
- **ADRs.** Write new append-only ADRs for: the C1 provider-construction fix and its readiness-contract implication; the C2/C3 limit-semantics changes; the H1 auth choice; the H7 readiness change; the H3/H4 trace-durability and structured-level changes; the M12 supersession of ADR-019.
- **ARCHITECTURE.md.** Add a "Day 4.5 amendments" section summarizing what changed and why. Do not rewrite §1–9.

**Commit:** `docs: record the Day 4.5 review fixes in ADR.md, ARCHITECTURE.md, and README`

---

## Final verification (do all of it, report the actual output)

```bash
# backend
cd backend
ruff check . && black --check . && mypy app && pytest -v

# frontend
cd ../frontend
npm run lint && npm run format:check && npm test && npm run build
```

Then, beyond the green checkmarks:

1. **Mutation-test the regressions.** For C1, C2, C3, C4, H3, and H4: reintroduce each bug one at a time, run the suite, and confirm the intended test **fails by name**. Report which test caught which bug. If a test passes against the reintroduced bug, that test is wrong — fix the test, not the report. This is the ADR-007 standard and it is the single most valuable thing in this repo's history.
2. **Verify C1 by hand:** start the app with `GEMINI_API_KEY` set and `OPENROUTER_API_KEY` unset, confirm `/health/ready` says `degraded`, then run a real session end-to-end and confirm it completes. The whole point of the fix is that those two agree.
3. **Verify C2 by hand:** send a task that makes the planner call the calculator with `9**9**9` and confirm it fails fast rather than hanging.
4. **Confirm the fork case:** the full backend suite passes with every secret unset.
5. **Tag** `day-4-review-fixes` when everything is green, and summarize in your final message: what you fixed, what you deliberately deferred and why, and anything in the findings list you disagree with after looking at the code — a finding you can argue is wrong is worth more than one you silently implement.
