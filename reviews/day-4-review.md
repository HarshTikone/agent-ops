# Agent Ops — code review through Day 4

**Reviewed:** `d4df774` (tag `day-4-complete`), working tree clean, 110 tracked files.
**Method:** full read of every source file, plus a running copy of the repo. Backend **83 passed / 29 skipped** (DB tests skip without `DATABASE_URL`), frontend **60 passed**, `ruff` / `black` / `eslint` / `prettier` all clean. Four findings below were reproduced by running code, and are marked **[reproduced]**.

**Two suspicions I checked and dropped** (recorded so nobody re-raises them):

- The `except ModelAPIError` clause in `gemini.py` / `openrouter.py` does *not* shadow the rate-limit/timeout clauses. `ModelAPIError`, `ModelRateLimitError`, `ModelTimeoutError`, and `ModelConnectionError` are all direct siblings under `ModelError` — verified against the installed `langchain-core`. The ordering is correct.
- The `MAX_TOOL_CALLS = 10` cap is not shadowed by LangGraph's recursion limit. In `langgraph` 1.2.11 the default is **10007** (`_internal/_config.py:32`), not the 25 of older versions, so ~50 supersteps for a maxed-out run is nowhere near it.

**Scope check:** every Day 4 item in `MASTER_PROMPT.md` is present — chat UI, trace viewer, approval modal, session list, loading/error states on every call, RTL component tests. Supabase Auth was optional and skipped, which is fine. Nothing from Day 5/6 has leaked in.

---

## Critical

### C1 — A Gemini-only ("degraded") deploy cannot serve a single request  **[reproduced]**

`app/dependencies.py:17` builds **both** providers eagerly:

```python
openrouter = OpenRouterProvider(api_key=settings.openrouter_api_key, model=settings.openrouter_model)
```

`ChatOpenAI` raises at *construction* when the key is empty:

```
OpenAIError: Missing credentials. Please pass an `api_key`, ... or set the `OPENAI_API_KEY` environment variable.
```

So with `GEMINI_API_KEY` set and `OPENROUTER_API_KEY` blank, every `POST /sessions/{id}/messages` and every approval call returns a bare 500. This **directly contradicts the readiness contract**: ADR-009 and `health.py`'s own docstring declare that state `degraded` — "can serve every request, just with no safety net if Gemini has an outage." It can serve nothing.

`OPENROUTER_MODEL` has the same shape of problem: `config.py:48` defaults it to `""` while `.env.example` supplies a real value, so a deploy that sets the key but not the model is equally broken.

No test catches this because CI always injects `secrets.OPENROUTER_API_KEY`, and the failure is at construction time in a dependency the unit tests never call.

**Fix:** construct the fallback lazily (or skip it entirely and return the bare `GeminiProvider`) when `openrouter_api_key` or `openrouter_model` is empty. Add a test that builds the provider with Gemini-only settings and asserts a working provider comes back.

### C2 — `calculator` is an unbounded DoS on LLM-controlled input  **[reproduced]**

`ast.Pow` is in the allow-list with no operand bound and no evaluation timeout. `9**9**9` did not return within an 8-second timeout — it pins a CPU and holds a threadpool worker indefinitely.

`expression` comes straight from whatever the planner LLM emits, which the module docstring correctly identifies as "effectively an LLM-controlled input string reaching Python." The AST allow-list closes *code execution*; it does nothing about *resource exhaustion*. And because of C4 below, the wedged session can never be retried.

`test_tools_calculator.py:20` explicitly asserts `"2 ** 10" == "1024"`, so the suite blesses the operator that carries the risk.

**Fix:** bound the exponent and operand magnitude before applying `Pow` (e.g. reject `abs(exponent) > 100` or a result exceeding ~1e15), cap `len(expression)`, and cap AST depth. Add tests for `9**9**9` and a 10k-char expression, each asserting a fast permanent `ToolError`.

### C3 — A fully successful 10-step plan is reported as `failed`  **[reproduced]**

`decide_next_node` checks the hard cap *before* the success branch:

```python
if state["tool_calls_made"] >= MAX_TOOL_CALLS:   # nodes.py:241
    ... give_up, status="failed"
if state["last_failure"] is None:                # nodes.py:251 — never reached
    ... finalize
```

Driving the node directly with a complete 10-step plan, last step succeeded, `tool_calls_made == 10`:

```
next_action: give_up | status: failed | answer: "Stopped after 10 tool calls without finishing the task."
```

The plan *did* finish. The cap should pre-empt **continuing**, not **finishing**.

**Fix:** move the cap check below the success/finalize branch, or gate it on `last_failure is not None or next_index < len(plan)`. Add a test for exactly-`MAX_TOOL_CALLS` successful steps asserting `finalize`.

### C4 — Any exception during a run wedges the session permanently

`sessions.send_message:81` and `approvals._decide:58` call `start_session_run` / `resume_session_run` with **no `try`/`except`**. `repo.start_session` has already flipped the row to `running`. So on any raise — C1, a C2 hang that eventually times out, a provider auth error, a DB blip — the client gets a bare 500 and the session stays `running` forever. A retry hits the `WHERE status='created'` guard and returns 409. Nothing ever moves it to `failed`.

The approval path is worse: `repo.decide_pending_action` already committed `approved`, but `mark_pending_action_executed` (line 70) is only reached if the resume *succeeds*, so a failed resume leaves an action stranded at `approved` on a session stuck at `awaiting_approval`.

**Fix:** wrap both calls; on exception, `update_session_status(..., status="failed", final_answer=<message>)`, write a `trace_events` row recording the crash, log with traceback, and return a 502/500 with a real detail. Add tests where the injected provider raises.

---

## High

### H1 — No authentication and no rate limiting on any endpoint

`GET /sessions` returns every session in the database to anyone who can reach the URL. `POST /approvals/{id}/approve` lets any caller execute the irreversible action the human-in-the-loop gate exists to guard — the entire premise of ADR-015/016 is defeated by an unauthenticated approve endpoint. `slowapi` sits in `requirements.txt` and is never imported. `allow_credentials=True` is set on CORS with no credentials in play.

ARCHITECTURE.md schedules rate limiting for Day 5, so the *timing* is defensible — but the deploy is Day 6 and this is the thing to have decided before then, not after.

### H2 — Multi-step persistence is non-transactional

`_apply_result` issues 2–4 independent autocommit statements. A failure between `create_pending_action` and `update_session_status` (`session_runner.py:59–62`) leaves a `pending` action on a session still marked `running` — the frontend only fetches `pending_action` when `status == 'awaiting_approval'`, so the modal never appears and the graph never resumes. The `done` path (`add_message` then `update_session_status`) has the same window.

**Fix:** take one connection and one explicit transaction for each `_apply_result` outcome.

### H3 — Trace persistence uses a count-based diff

```python
already_persisted = len(repo.list_trace_events(pool, session_id))   # session_runner.py:48
for event in trace[already_persisted:]:
```

Two problems. It `SELECT`s every column of every row purely to take `len()` (should be `COUNT(*)`). And it assumes DB row count and in-state trace length never diverge — any partial insert, manual delete, or concurrent write permanently drops or duplicates events, silently. For a project whose stated thesis is "the trace IS the product" (ARCHITECTURE §0), this is the wrong durability story.

**Fix:** persist a monotonic per-session sequence number with each event and diff on that, or write trace rows inside the same transaction as H2.

### H4 — `trace_events.provider` is never written

The column exists (`0001_initial_schema.sql:40`), `TraceEventResponse.provider` exposes it, and `TraceViewer.tsx:81` renders `via {provider}` — but `session_runner.py:50` never passes `provider=`, so it is always `NULL` and that UI branch is dead. `GraphState`'s `TraceEvent` TypedDict has no `provider` field to carry it. The only record of which provider answered is scraped out of free text in `detail`. Making the failover *observable* is the whole payoff of ADR-002.

**Fix:** add `provider: str | None` to `TraceEvent`, set it in `planner_node` / `finalize_node` from `response.provider`, pass it through `_persist_new_trace_events`.

### H5 — TypeScript `strict` is off  **[reproduced]**

Neither `tsconfig.app.json` nor `tsconfig.node.json` sets `strict`, `strictNullChecks`, `noImplicitAny`, or `noUncheckedIndexedAccess` — the Vite React-TS template ships `"strict": true` and it was dropped. For a repo whose selling point includes discriminated-union load states and exhaustive `Record<Status, …>` maps, the compiler is checking far less than the code implies.

I enabled `strict` **and** `noUncheckedIndexedAccess` and rebuilt: **exactly one error**, in a test file (`src/lib/api.test.ts:75`, destructuring a possibly-`undefined` array). This is a five-minute fix that currently buys nothing.

### H6 — No type checker in CI for the backend; mypy finds 5 real errors  **[reproduced]**

`mypy` isn't in `requirements-dev.txt` or `ci.yml`. Running `mypy app --ignore-missing-imports`:

- `app/tools/registry.py:23,24,25` — **all three tools structurally violate the `Tool` Protocol.** `Tool.run` is declared `def run(self, **kwargs: Any) -> str`; the implementations are `run(self, *, expression: str)`, `run(self, *, action, key, content)`, `run(self, *, query: str)`. The Protocol is decorative — it would not catch a tool with a genuinely wrong `run` shape, which is precisely the "uniform tool-adapter interface" the file claims to enforce.
- `app/api/sessions.py:89` and `app/api/approvals.py:73` — `repo.get_session(...)` returns `dict | None` and is passed straight into `session_with_pending_action(pool, session)`, which subscripts it. A session deleted between two statements gives `TypeError: 'NoneType' object is not subscriptable` → 500.

### H7 — `/health/ready` never touches the database

It checks only that config *strings are non-empty*. README documents that Supabase free projects pause after 7 days of inactivity — against a paused project this endpoint reports `ready`. That is exactly the failure the docstring says it exists to surface ("should fail loudly in a demo if…"). A readiness probe should dial its dependencies: `SELECT 1` through the pool, with a short timeout, and downgrade to `not_ready` on failure.

### H8 — CI can't run on forks, and shares one live database

The backend job depends on `secrets.GEMINI_API_KEY` / `DATABASE_URL` / etc. Fork PRs receive empty secrets: DB tests skip and the live-Gemini tests fail. Beyond that, all runs hit **one shared Supabase project** — `test_list_sessions_endpoint_returns_most_recent_first` reads globally-visible rows, so two concurrent branch runs can interfere — and migrations are assumed already applied rather than run by the job.

**Fix:** a `postgres` service container (with `pgvector`) plus a `migrate.py` step for the DB tests, and put the live-LLM tests behind an opt-in marker (`-m live`) that only runs on `main` or on demand.

---

## Medium

| # | Finding |
|---|---|
| M1 | `db.get_db_pool()` opens a `ConnectionPool` that is **never closed** — there is no FastAPI `lifespan`. It also uses `open=True` in the constructor (the form `psycopg_pool` deprecates) and sets no `check=`, so a Supabase idle-drop hands out a dead connection on the next request. |
| M2 | `WebSearchTool.__init__` creates an `httpx.Client` and nothing ever closes it. `build_tool_registry` runs on **every** `.invoke()`, so each request leaks a client and its connection pool. |
| M3 | `update_session_status` always includes `final_answer` in the `SET` clause with a `None` default, so every status-only update (e.g. `awaiting_approval`) silently nulls any answer already stored. |
| M4 | `mark_pending_action_executed` runs *after* the resume (see C4), and the `executed` state is otherwise write-only — no query, endpoint, or UI ever reads it. |
| M5 | No server-side input validation: `CreateMessageRequest.content` has no `min_length`/`max_length` (empty tasks are only blocked client-side in `ChatPanel`), `RejectRequest.reason` is unbounded, `GET /sessions` hardcodes `limit=50` with no query param, `GET /sessions/{id}/trace` is unbounded. |
| M6 | `notes_store.run` catches only `psycopg.OperationalError`. A `DataError` / `ProgrammingError` (oversized key, bad encoding) escapes as a raw exception through `tool_call_node`, which only catches `ToolError` — breaking ARCHITECTURE §6's "every tool failure is caught at the adapter boundary." |
| M7 | `web_search.run` catches only `TimeoutException` / `ConnectError`. `httpx.ReadError`, `RemoteProtocolError`, `TooManyRedirects` escape the same way. Catch `httpx.HTTPError` as the base. |
| M8 | `_eval_node` recurses without a depth bound; a deeply nested expression raises `RecursionError`, which is not in the `except (TypeError, OverflowError, ValueError)` tuple and so escapes as a non-`ToolError`. |
| M9 | Backend `Dockerfile`: runs as **root**; `build-essential` is installed and never removed; `migrations/` and `scripts/` are **not copied**, so `migrate.py` cannot be run from the image on Render; no `HEALTHCHECK`; declares `AS base` for a multi-stage structure it never uses. |
| M10 | Three declared runtime dependencies are never imported: `tenacity`, `structlog`, `slowapi`. `structlog` in particular contradicts the structured-logging story — the app uses `logging.basicConfig`. |
| M11 | `ApprovalModal` is not a real modal: `role="dialog" aria-modal="true"` with no focus trap, no initial focus, no Escape handler, and no `inert`/`aria-hidden` on the background. Keyboard and screen-reader users can tab straight into the page behind the overlay — on the one dialog in the app that gates an irreversible action. |
| M12 | `TraceViewer.toneFor` colors rows by substring-matching free-text `detail`. ADR-019 owns this as a deliberate trade, but it misfires today: a planner line whose tool args contain the word "retry" or "replan" renders amber. Fixing H4's sibling — emitting a structured `level` — removes the guesswork. |

---

## Low / nits

1. `main.py` — no `lifespan`, no global exception handler; `logging.basicConfig` at import time is a no-op if logging is already configured (e.g. under Gunicorn); `settings.port` is read from env and never used.
2. `api.ts:6` — `VITE_API_URL ?? 'http://localhost:8000'` silently points a production build at localhost. Fail loudly when `import.meta.env.PROD` and the var is unset.
3. `SessionPage.runAction` calls `refetch()` with no `AbortSignal` and doesn't special-case `AbortError`; unmounting mid-action sets state on a dead component and shows a spurious error.
4. `ChatPanel` — chat errors are suppressed whenever a `pending_action` exists (`error={load.session.pending_action ? null : actionError}`); Enter doesn't submit; no `maxLength` on the textarea.
5. `ApprovalModal` — only Approve shows "Working…"; Reject keeps its label while submitting.
6. `BackendStatus` renders raw field names ("gemini_api_key_set missing") rather than human labels.
7. No `*` catch-all route and no React error boundary — `/sessions/<garbage>` renders a blank page under the header.
8. **`frontend/README.md` is the untouched Vite scaffold boilerplate**, referring to Oxlint (the project uses ESLint), the React Compiler, and `plugin-react-swc`. Committed noise in a repo whose purpose is to be read.
9. Root `README.md` still says "**Status: Day 1 of a 7-day build**" and documents none of `GET /sessions`, `GET /sessions/{id}`, or the frontend routes.
10. `ARCHITECTURE.md` §6 names `SUPABASE_SERVICE_KEY`; the variable is `SUPABASE_SECRET_KEY` everywhere else.
11. `GEMINI_MODEL`'s default is duplicated in `config.py` and `.env.example`; `VITE_API_URL` appears in both the root and `frontend/` `.env.example`.
12. Migration `0002` uses `DROP CONSTRAINT sessions_status_check` without `IF EXISTS`; `migrate.py` takes no advisory lock (documented as acceptable) and only imports `app` if run with `backend/` as CWD.
13. No index on `sessions (created_at DESC)` backing `list_sessions`' `ORDER BY … LIMIT`.
14. `list_sessions` + `session_with_pending_action` is an N+1 — one extra query per `awaiting_approval` row.
15. `conftest.db_pool` is session-scoped against a shared real database; isolation depends on no concurrent runner (see H8).
16. `nginx.conf` — no gzip, no cache headers for hashed assets, no security headers; the image runs nginx as root.
17. Pre-commit hooks shell out via `bash -c 'cd … && …'`, fragile on the Windows box this repo is developed on; `pass_filenames: false` means each hook lints the whole tree.
18. `pyproject.toml` sets `asyncio_mode = "auto"` but there is not a single async test.
19. `LLMProvider` isn't `@runtime_checkable`, and `FailoverProvider` has no `name` attribute even though `failover.py` does `getattr(provider, "name", …)` on its children.
20. `observe_node` dedupes prior `ToolMessage`s by `tool_call_id`; two planner steps sharing an id would silently collide.
21. `EXPOSE 8000` is hardcoded in the backend Dockerfile while the port is `$PORT`-driven.
22. No Dependabot config, no CodeQL, no coverage threshold in CI despite `@vitest/coverage-v8` being installed and a `test:coverage` script existing.

---

## What's genuinely good

Worth stating, because a flaw list reads as a verdict and this isn't one.

- **The exception-translation boundary** (`gemini.py` / `openrouter.py` / `errors.py`) is right, and right for a reason that's written down and was verified against the installed packages rather than assumed — including the asymmetry where only one of the two integrations normalizes timeouts.
- **`decide_next` as one explicit node** rather than an if-chain smeared across the others is the correct call, and it's the piece most worth talking through in an interview.
- **`approval_gate` isolated from `tool_call`** because LangGraph replays a node body from the top on resume is a subtle, load-bearing insight, and the comment explaining it is better than most production code's.
- **ADR-007's mutation-testing story** — tests that passed against the reintroduced bug — remains the strongest artifact in the repo.
- **ADR-013's "two real bugs no mocked test caught"** (`.text` vs `.content`; duplicate `ToolMessage` for one `tool_call_id` returning 200-with-empty-content) is exactly the failure-mode evidence portfolio reviewers ask for and rarely get.
- Test suites are real: `_FakeTransport` over `httpx` instead of `unittest.mock` guesswork, and RTL tests that assert on roles and behavior rather than implementation.

The recurring shape across C1, H4, H6, and H7 is the same one: **a contract is stated in a docstring or an ADR, and nothing executable enforces it.** `degraded` claims serviceability nothing checks; the `Tool` Protocol claims uniformity mypy would reject; `/health/ready` claims readiness it never dials; `provider` is plumbed end-to-end except for the one line that writes it. That's the theme worth fixing, more than any individual bug.
