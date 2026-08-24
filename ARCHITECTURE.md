# Architecture — Agent Ops

Agent Ops is a multi-agent orchestration copilot: a planner agent decomposes
an incoming task into steps, delegates each step to a tool-using sub-agent,
and pauses for human approval before any irreversible action executes. Every
decision, tool call, and its reasoning is persisted and rendered in a trace
viewer — the trace *is* the product, not a debugging afterthought.

This document describes the system as designed on Day 1. It will be amended,
not rewritten, as later days add real code — if an amendment changes a
decision recorded in `ADR.md`, that gets a new ADR entry, not a silent edit
here.

## 1. System overview

```mermaid
flowchart TB
    subgraph Client["Frontend (React + Vite, Vercel)"]
        UI[Chat UI]
        Trace[Trace Viewer]
        Approve[Approval Modal]
    end

    subgraph API["Backend (FastAPI, Render)"]
        REST["/sessions, /messages,\n/approvals, /trace endpoints"]
        Graph["LangGraph agent graph\n(planner -> delegate -> tool-call\n-> observe -> decide-next)"]
        Provider["LLMProvider interface"]
        Tools["Tool adapters:\nweb search / notes store / calculator"]
    end

    subgraph LLM["LLM providers"]
        Gemini[Gemini API - primary]
        OpenRouter[OpenRouter :free model - fallback]
    end

    subgraph Data["Supabase Postgres + pgvector"]
        Sessions[(sessions)]
        Messages[(messages)]
        TraceLog[(trace_events)]
        Approvals[(pending_actions)]
        Memory[(session_memory / embeddings)]
    end

    UI -->|HTTP| REST
    Approve -->|approve/reject| REST
    Trace -->|poll/stream| REST
    REST --> Graph
    Graph --> Provider
    Provider -->|primary| Gemini
    Provider -->|on failure, fallback| OpenRouter
    Graph --> Tools
    Graph --> TraceLog
    Graph --> Approvals
    REST --> Sessions
    REST --> Messages
    REST --> Memory
```

## 2. Component responsibilities

**Frontend (`frontend/`)** — React + TypeScript + Vite + Tailwind. Renders
the chat, a trace panel showing each agent decision and tool call as it
happens (not just the final answer — this is the project's differentiator,
per the brief), an approval modal that blocks on a real pending action, and a
session list. Talks to the backend only over the documented REST API; holds
no LLM keys and no direct DB connection.

**Backend (`backend/`)** — FastAPI. Owns the LangGraph agent graph, the
provider failover, tool adapters, the approval state machine, and all
Supabase access (service-role key never leaves the backend). Exposes:
session CRUD, message send, approve/reject, and trace fetch endpoints (built
out Day 3).

**Agent graph** — a LangGraph state graph with (at minimum) these node
types, built Day 2:

- **planner** — decomposes the incoming task into an ordered/branching list
  of steps.
- **delegate** — routes a step to the sub-agent responsible for it (web
  search / notes store / calculator, initially — more tools can be added
  without changing this shape).
- **tool-call** — invokes the concrete tool adapter; catches and logs every
  failure (network error, malformed args, tool-side error) rather than
  letting an exception cross the graph boundary silently.
- **observe** — folds the tool's result (or failure) back into graph state.
- **decide-next** — given the updated state, decides whether to proceed to
  the next planned step, re-plan (if a step failed in a way that changes the
  plan), retry (if the failure looks transient), or request human approval
  before an irreversible step.

Every node transition writes a trace event: which node ran, what it decided,
which tool (if any) it called, what came back, and why it chose the next
node. This is the raw material the Day 4 trace viewer renders.

**LLMProvider interface** — one abstract interface (`generate(messages,
tools) -> response`) with two concrete implementations (`GeminiProvider`,
`OpenRouterProvider`, see ADR-002) and a `FailoverProvider` that composes
them: try Gemini, and on a timeout/5xx/rate-limit, transparently retry on
OpenRouter, logging the failover itself as a trace event. The planner graph
depends only on the interface, never on a concrete provider — swapping or
adding a third provider later touches one file.

**Tools (Day 2 minimum set)**

1. **Web search** — external information lookup.
2. **Notes / document store** — read/write persistent notes scoped to a
   session (backed by Supabase; this is also where embeddings/pgvector would
   be used if a step needs semantic recall over prior notes).
3. **Calculator / code-exec** — deterministic computation, kept separate from
   the LLM's own arithmetic to avoid the well-known failure mode of language
   models silently getting arithmetic wrong.

Each tool adapter has a uniform interface (`name`, `description`,
`args_schema`, `run`) so the planner's tool-selection logic doesn't special-
case any one tool, and each adapter's failure path is exercised by a test
(Day 2 requirement: at least one shown failure mode per feature area).

**Approval state machine (Day 3)** — a real state machine, not a UI-only
gate: `pending -> approved -> executed` or `pending -> rejected` (terminal).
Persisted in Supabase (`pending_actions` table) so a pending approval
survives a backend restart or a page reload — the frontend's approval modal
is a view onto this state, not the source of truth for it.

**Trace log (Day 3)** — append-only `trace_events` table: one row per agent
decision or tool call, with session id, node name, input, output/error,
reasoning text, timestamp, and provider used (Gemini vs. OpenRouter, so a
failover is visible in the trace itself).

**Memory (Day 3)** — `session_memory` table (plus pgvector embeddings column
for any semantic recall the agents need across a long session or across
sessions). Distinct from the trace log: memory is what the agent is allowed
to *use* as context; the trace log is a record of what it *did*, kept even
for context that later gets pruned from the active memory window.

## 3. Data flow — one step, happy path

1. User sends a message via `POST /sessions/{id}/messages`.
2. Backend loads session memory + trace context, invokes the LangGraph graph.
3. **planner** node decomposes the task (or continues an existing plan).
4. **delegate** picks the tool for the current step.
5. If the step is irreversible (e.g. a write that can't be undone), the graph
   transitions to a `pending` approval row instead of calling the tool, and
   returns to the frontend with an `awaiting_approval` status. Execution
   pauses here — literally, the graph run ends and is resumed later by a
   separate `POST /approvals/{id}/approve` call, not held open in memory.
6. **tool-call** invokes the tool adapter through the `LLMProvider`-agnostic
   tool interface (tools may or may not use the LLM themselves).
7. **observe** records the result (or failure) into state and the trace log.
8. **decide-next** picks the next node: another step, re-plan, retry, or
   done.
9. Every node's decision is written to `trace_events` as it happens, so the
   frontend's trace viewer can show progress live rather than only after the
   whole run completes.

## 4. Data flow — failure path (Gemini outage)

1. **tool-call** or **planner** node calls `LLMProvider.generate(...)`.
2. `FailoverProvider` calls Gemini; Gemini times out / returns 429 / 5xx.
3. Failure is logged as its own trace event (`provider_failover`,
   `from=gemini`, `to=openrouter`, reason).
4. `FailoverProvider` retries the same request against the pinned OpenRouter
   `:free` model.
5. If OpenRouter also fails, the error surfaces to **decide-next**, which
   either retries the whole step once (transient-looking failure) or
   re-plans (the step itself looks wrong, not just the provider call) —
   never silently drops the step. This exact path (mocked Gemini failure ->
   OpenRouter call observed, plus the retry/re-plan branch) is Day 2's
   required test, not just a design intention.

## 5. Deployment topology

- **Backend** → Render free web service, auto-deploy on push to `main`,
  Dockerized (Day 6). Cold-starts after 15 minutes idle (~30-60s first
  request) — expected and documented, not a bug.
- **Frontend** → Vercel Hobby, auto-deploy on push to `main`, connected to
  the same GitHub repo.
- **Database** → Supabase Postgres (pgvector enabled). Free project pauses
  after 7 days of total inactivity; README documents how to wake it.
- **CI** → GitHub Actions on every push: lint (ruff/eslint) + test
  (pytest/vitest) + build, required to pass before merge to `main` via
  branch protection (added Day 6).

## 6. Cross-cutting concerns (owned from Day 1, expanded through the week)

- **Every tool failure is caught and logged, never silently swallowed**
  (Day 2 hard requirement) — enforced at the tool-adapter boundary, not
  hoped for at the call site.
- **Human approval is a real state machine**, persisted server-side
  (Day 3), so the UI cannot fake an approval by just hiding a modal.
- **Rate limiting / per-session tool-call caps** (Day 5) exist specifically
  so a mis-planned agent loop cannot burn a full day's 50-request OpenRouter
  budget or an unknown Gemini free quota in one runaway session.
- **Secrets** never enter the frontend bundle or a committed file — only
  `backend/` reads `GEMINI_API_KEY` / `OPENROUTER_API_KEY` /
  `SUPABASE_SERVICE_KEY`; the frontend only ever talks to our own backend.

## 7. Day 2 amendments — what actually got built

Per this document's own header: amended below, not rewritten above. Two
places where the real code (`backend/app/llm/`, `backend/app/tools/`,
`backend/app/graph/`) differs from Day 1's design, plus what's unchanged.

**A sixth node, `finalize`, was added.** §2/§3 describe five node types.
Once a plan's steps all succeed, something has to turn the raw tool outputs
into a natural-language answer — `finalize` makes one more LLM call (no
tools bound) over the full message history and produces `final_answer`.
When the planner's first LLM call needs no tool at all, the graph routes
straight to `END` instead — `finalize` is skipped, since the planner's own
answer already *is* the final answer.

**`decide_next` is a node plus a router, not a bare conditional function.**
LangGraph's conditional edges can only return a next-node name — they can't
themselves mutate state. So `decide_next_node` is a real node that computes
the retry/replan/give-up decision *and* writes it into `state["next_action"]`
plus whatever counters that decision implies (`step_index`, `step_attempts`,
`replans`); a one-line `route_after_decide` immediately after just reads
`next_action` back out. See ADR-012 for the decision logic itself.

**Everything else matches the design as written:** the `LLMProvider`
interface and `FailoverProvider` composition (§2, ADR-002, and now ADR-010
for the concrete exception-translation mechanics), the uniform tool-adapter
interface (§2), tool failures caught and logged at the tool-call boundary
and never crossing it raw (§6), and graph state staying in-memory for Day 2
(§2's Day 3 note) — `app/graph/state.py`'s `trace` list is exactly the
lightweight stand-in for the real `trace_events` table described there.

## 8. Day 3 amendments — memory, approval, tracing, and the API

**A seventh node, `approval_gate`, sits between `delegate` and `tool_call`.**
`delegate -> approval_gate -> tool_call -> observe -> decide_next`. It's a
no-op pass-through for every step except the one irreversible action in
Day 3's tool set (`notes_store` with `action="write"` — ADR-016); for that
one, it's the only node that ever calls LangGraph's `interrupt()`. See
ADR-015 for why it's a separate node rather than a check inside
`tool_call`.

**§2's "graph state stays in-memory for Day 2" is now superseded, not just
extended.** ADR-014 confirms ADR-001's original claim that LangGraph ships
real checkpointing: `GraphState` (including the full message history, plan,
and retry/replan counters) is persisted via `PostgresSaver` against the
real Supabase project, keyed by `thread_id = str(session_id)`. This is what
makes §3 step 5's "the graph run literally ends, resumed later by a
separate request" true in practice, not just in the design doc — verified
live across two independently-constructed `PostgresSaver`/compiled-graph
instances (simulating two separate HTTP requests) before any application
code was written around it.

**`sessions.status` gained a `created` state**, ahead of `running`: `POST
/sessions` creates a session with no task yet; the first
`POST /sessions/{id}/messages` call supplies it and starts the graph. This
matches §3 step 1's literal ordering ("User sends a message via `POST
/sessions/{id}/messages`") — §3 didn't previously spell out that session
creation has its own separate, task-less step.

**Endpoints match §1's diagram exactly:** `POST /sessions`,
`GET /sessions/{id}`, `POST /sessions/{id}/messages`,
`GET /sessions/{id}/trace`, `POST /approvals/{id}/approve`,
`POST /approvals/{id}/reject`. No session-listing or pending-action-listing
endpoint yet (ADR-015's "what we gave up" — deferred to Day 4 once the UI
shape is known).

**`session_memory` has no `embedding` column yet.** §2 describes it as
"session_memory table (plus pgvector embeddings column for any semantic
recall the agents need)" — the `vector` extension is enabled
(`CREATE EXTENSION IF NOT EXISTS vector`) per the original stack plan, but
no code generates embeddings this day, so no column was added for one with
a guessed dimension. `notes_store` (ADR-011, repointed at this table per
its own Day 2 promise) is a plain key/value store today; semantic recall
over notes is deferred until something actually needs it.

**Cross-cutting concern added:** LangGraph's own checkpoint tables
(`checkpoints`/`checkpoint_blobs`/`checkpoint_writes`) have no foreign key
back to `sessions` and are not cleaned up when a session's other rows are
deleted — flagged in ADR-014 as a real, currently-unaddressed gap relevant
to Supabase's free-tier storage cap (§5, ADR-003), not yet a Day 3
requirement to fix (no `DELETE /sessions/{id}` endpoint exists).
