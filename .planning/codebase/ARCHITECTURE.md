<!-- refreshed: 2026-08-25 -->
# Architecture

**Analysis Date:** 2026-08-25

## System Overview

Agent Ops is a multi-agent orchestration platform structured around a **planner-delegate-executor** pattern, where a primary LLM decomposes incoming tasks into steps, a graph coordinates execution with human-in-the-loop approval gates, and tool-using sub-agents execute each step. Every decision and tool call is traced and persisted, enabling full observability and auditability of agent reasoning.

```text
┌──────────────────────────────────────────────────────────────┐
│         Frontend (React + TypeScript + Vite)                  │
│  ┌─────────────┬──────────────┬─────────────────────────┐   │
│  │ SessionList │  SessionPage │   Approval + Trace UI   │   │
│  │ (routes)    │  (chat/trace)│   (visualization layer) │   │
│  └─────────────┴──────────────┴─────────────────────────┘   │
│                              │                                │
│                         (sync HTTP)                           │
│                              │                                │
├──────────────────────────────────────────────────────────────┤
│              Backend (FastAPI + LangGraph)                    │
│  ┌──────────────┬────────────────┬──────────────────────┐   │
│  │ API routers  │ Graph engines  │  Tool adapters       │   │
│  │ (CRUD+run)   │ (plan/execute) │  (calc/notes/search) │   │
│  └──────────────┴────────────────┴──────────────────────┘   │
│                              │                                │
│           ┌───────────────┬──────────┬─────────────┐         │
│           │               │          │             │         │
│           ▼               ▼          ▼             ▼         │
│     ┌─────────────────────────────────────────────────────┐ │
│     │  LLMProvider interface (Gemini + OpenRouter)        │ │
│     │  with automatic failover                            │ │
│     └─────────────────────────────────────────────────────┘ │
│                                                               │
│     ┌─────────────────────────────────────────────────────┐ │
│     │  Database layer (raw SQL + psycopg + checkpointer) │ │
│     └─────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│           External Services (LLM + Database)                  │
│   Gemini API / OpenRouter API / Supabase Postgres             │
└──────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Purpose | File |
|-----------|---------|------|
| **SessionList** | Lists all sessions with status; "New session" button | `frontend/src/pages/SessionListPage.tsx` |
| **SessionPage** | Single session view; task input, chat, trace, approval modal | `frontend/src/pages/SessionPage.tsx` |
| **API Routers** | HTTP endpoints: POST/GET sessions, messages, trace, approve/reject | `backend/app/api/sessions.py`, `approvals.py`, `health.py` |
| **Graph Builder** | Wires LangGraph nodes into a state machine with checkpointing | `backend/app/graph/build.py` |
| **Graph Nodes** | planner, delegate, approval_gate, tool_call, observe, decide_next, finalize | `backend/app/graph/nodes.py` |
| **LLMProvider** | Protocol interface + Gemini + OpenRouter + failover composition | `backend/app/llm/base.py`, `gemini.py`, `openrouter.py`, `failover.py` |
| **Tool Adapters** | Uniform interface (name, description, args_schema, run) for calc, notes, search | `backend/app/tools/` directory |
| **Repository** | CRUD helpers: sessions, messages, trace_events, pending_actions | `backend/app/repository.py` |
| **Session Runner** | Bridges graph execution to database persistence; handles checkpointing | `backend/app/session_runner.py` |

## Pattern Overview

**Overall:** Event-sourced workflow engine with deferred human approval.

**Key Characteristics:**
- **Task → Plan → Execute → Trace** pipeline runs synchronously within a single HTTP request or pauses for approval and resumes via a separate request
- **Graph state is durable** — LangGraph's `PostgresSaver` checkpoints full session state to Supabase, allowing multi-day sessions and interrupts that survive backend restarts
- **One task per session** (enforced at the API boundary in `sessions.py`) — a session's first message supplies the task and triggers graph execution; no second task per session
- **Real approval state machine** (not a UI feature) — pending action rows in the database are the source of truth; the frontend's modal is just a view
- **Provider failover is transparent** — caller code never sees which provider answered; it's only visible in the trace_events table

## Layers

**HTTP Request/Response Layer:**
- Purpose: Translate HTTP into graph invocation; translate graph state into session responses
- Location: `backend/app/api/`, `backend/app/main.py`, `backend/app/dependencies.py`
- Contains: FastAPI routers, dependency injection (get_llm_provider, get_db_pool, get_checkpointer)
- Depends on: Graph builder, repository, LLMProvider, database connection pool
- Used by: Frontend (React) via fetch API

**Session Orchestration Layer:**
- Purpose: Run a session's graph from start to finish or to an approval interrupt; persist state to database
- Location: `backend/app/session_runner.py`
- Contains: Main entry point that invokes graph, applies results to database
- Depends on: Graph builder, repository, checkpointer
- Used by: API routers (`send_message`, `approve`, `reject` endpoints)

**Graph Execution Layer:**
- Purpose: Coordinate planner → delegate → execute → decide-next → finalize flow
- Location: `backend/app/graph/build.py`, `backend/app/graph/nodes.py`, `backend/app/graph/state.py`
- Contains: Node implementations, state definition, conditional edges
- Depends on: LLMProvider, tool registry, graph state type
- Used by: Session runner

**LLM Abstraction Layer:**
- Purpose: Provide a unified interface to multiple LLM providers with automatic failover
- Location: `backend/app/llm/`
- Contains: LLMProvider protocol, Gemini + OpenRouter implementations, FailoverProvider composition
- Depends on: langchain-google-genai, langchain-openai
- Used by: Planner and finalize nodes

**Tool Adapter Layer:**
- Purpose: Provide uniform interface for diverse external tools (calculator, notes, web search)
- Location: `backend/app/tools/`
- Contains: Tool protocol, registry, adapter implementations
- Depends on: External APIs (Tavily for web search), database (notes)
- Used by: tool_call node, delegate node

**Persistence Layer:**
- Purpose: Manage all database operations — sessions, messages, trace, approvals, checkpoints
- Location: `backend/app/repository.py`, `backend/app/db.py`
- Contains: CRUD functions, connection pool, checkpointer factory
- Depends on: psycopg, langgraph-checkpoint-postgres
- Used by: Session runner, API routers, tool adapters (notes store)

## Data Flow

### Primary Request Path (Happy Case)

1. **User creates a session** (`POST /sessions`)
   - `sessions.py:create_session` → `repo.create_session` → Supabase `sessions` table
   - Returns session with status='created'

2. **User sends task** (`POST /sessions/{id}/messages`)
   - `sessions.py:send_message` validates session status is 'created'
   - `repo.start_session` updates status='running' and records task
   - `session_runner.start_session_run` invokes the compiled graph

3. **Graph execution** (within `.invoke()` call, synchronous)
   - **planner node** calls LLMProvider with full message history and available tools
   - LLMProvider tries Gemini; on failure (timeout/429/5xx), FailoverProvider retries on OpenRouter
   - Response (tools to call, or final answer if no tools needed) is logged to trace_events
   - **route_after_planner** decides: if tools, go to delegate; if no tools, go to END

4. **For each planned step** (loop: delegate → approval_gate → tool_call → observe → decide_next)
   - **delegate** logs which step index, tool name, and arguments
   - **approval_gate** checks if (tool_name, action) is in IRREVERSIBLE_STEPS (e.g., "notes_store"/"write"); if yes, calls interrupt()
   - **interrupt()** pauses execution, raises exception caught by session_runner
   - session_runner creates pending_action row, updates session status='awaiting_approval', returns to frontend with 200 OK

5. **Frontend shows approval modal** (syncs trace, renders pending action details)

6. **User clicks Approve** (`POST /approvals/{id}/approve`)
   - `approvals.py:approve_pending_action` updates pending_action status='approved'
   - `session_runner.start_session_run` is called again with same thread_id (via checkpointer)
   - LangGraph resumes from the interrupt, continues execution

7. **tool_call executes the tool** (same step, now approved)
   - Calls tool.run() with the arguments from the plan
   - Catches ToolError, logs to trace_events, doesn't propagate

8. **observe** logs result to state and trace_events

9. **decide_next** evaluates:
   - Success: advance to next step (or finalize if last step)
   - Transient failure (rate limit, timeout): retry (up to MAX_STEP_RETRIES)
   - Plan error (bad args): replan (up to MAX_REPLANS)
   - Too many retries/replans: give_up (end with failed status)

10. **finalize node** (once all plan steps succeed)
    - Calls LLMProvider again with full message history, asking for a natural-language answer
    - Logs response as final_answer, sets status='done'
    - Graph reaches END

11. **session_runner applies result**
    - Persists trace_events, updates session status, adds assistant message
    - Returns to API, which responds with updated session

12. **Frontend re-fetches session + trace** and renders final answer

### Approval Rejection Path

Same as above, but at step 5:

- **User clicks Reject** (`POST /approvals/{id}/reject`)
- `approvals.py:reject_pending_action` updates pending_action status='rejected'
- Calls `decide_next` with a special flag indicating rejection
- `decide_next` sets status='failed', writes rejection reason to final_answer
- Graph ends with failed status, frontend shows rejected state

### Provider Failover Trace

1. Planner node calls `llm.generate(messages, tools)`
2. FailoverProvider.generate tries Gemini; times out or returns 429
3. FailoverProvider logs failover to trace_events: `node=provider_failover, detail="from=gemini, to=openrouter"`
4. FailoverProvider retries same request against OpenRouter :free model
5. If OpenRouter succeeds, returns LLMResponse with provider="openrouter"
6. If OpenRouter also fails, raises exception, caught by decide_next, triggers retry or replan

**State Management:**
- In-memory during graph execution: `GraphState` (messages, plan, step_index, trace, etc.)
- Between requests: PostgresSaver checkpoints GraphState to Supabase `checkpoints` + `checkpoint_blobs` tables
- Per-session trace: append-only `trace_events` table (one row per decision/tool call)
- Approvals: `pending_actions` table with status ('pending', 'approved', 'rejected', 'executed')
- Session metadata: `sessions` table (id, task, status, final_answer, created_at, updated_at)
- Tool-specific state: `session_memory` table (notes, per-session key-value store)

## Key Abstractions

**GraphState (TypedDict):**
- Purpose: The single source of truth for a session's execution state
- Location: `backend/app/graph/state.py`
- Fields: task, messages, plan, step_index, step_attempts, replans, tool_calls_made, last_result, last_failure, next_action, status, final_answer, trace
- Pattern: Immutable across node boundaries; nodes return dict partials that StateGraph merges

**LLMProvider (Protocol):**
- Purpose: Abstract away concrete provider implementation
- Examples: `GeminiProvider`, `OpenRouterProvider`, `FailoverProvider`, test doubles
- Pattern: Structural typing (Protocol), not inheritance; enables dependency injection and testing

**Tool (Protocol):**
- Purpose: Uniform interface for diverse tools
- Examples: `CalculatorTool`, `NotesStoreTool`, `WebSearchTool`
- Pattern: Structural typing; each tool is a class with name, description, args_schema (Pydantic), and run() method

**Interrupt/Resume Loop:**
- Purpose: Pause execution for human approval without holding connection open
- Pattern: LangGraph's interrupt() raises exception, caught by session_runner, pending_action row created; later request with same thread_id resumes from checkpoint

**TraceEvent:**
- Purpose: Immutable record of every decision or tool call
- Structure: {node, detail, provider (nullable), created_at}
- Pattern: Append-only; grows throughout session; frontend renders in order

## Entry Points

**HTTP Entry (Backend):**
- Location: `backend/app/main.py`
- Triggers: FastAPI startup, server listening on port 8000
- Responsibilities: Configure CORS, include routers, serve /docs

**Session Creation:**
- Location: `backend/app/api/sessions.py:create_session` (POST /sessions)
- Triggers: User clicks "New session"
- Responsibilities: Create sessions row, return session with status='created'

**Graph Execution:**
- Location: `backend/app/api/sessions.py:send_message` (POST /sessions/{id}/messages)
- Triggers: User sends first (and only) message to a session
- Responsibilities: Validate session status, call session_runner.start_session_run, catch exceptions, update session status

**Frontend Entry:**
- Location: `frontend/src/main.tsx`
- Triggers: Page load in browser
- Responsibilities: Render React app, establish BrowserRouter context

**Router Dispatch:**
- Location: `frontend/src/App.tsx`
- Triggers: Any route navigation
- Responsibilities: Switch between SessionListPage (/) and SessionPage (/sessions/:sessionId)

## Architectural Constraints

- **Threading:** Single-threaded event loop (FastAPI/Uvicorn); tool calls and LLM requests are blocking synchronous calls within the event loop, not async
- **Global state:** `get_settings()` is a cached singleton (LRU); `get_db_pool()` dependency returns a shared ConnectionPool instance per process
- **Circular imports:** None detected; layers strictly separate (HTTP → Session Runner → Graph → Tools/LLM)
- **One task per session:** Enforced by repo.start_session's WHERE clause and 409 response in API
- **Graph state durability:** PostgresSaver is the only checkpointer; in-memory checkpointing only used in tests
- **Trace append-only:** trace_events table is insert-only; no updates or deletes
- **No ORM:** Raw psycopg SQL for simplicity; schema is small enough that SQLAlchemy overhead isn't justified (see ADR-014)

## Anti-Patterns

### Silent Tool Failures

**What happens:** Tool execution errors (network timeouts, malformed args, external service failures) are caught at the tool-call boundary and logged, never propagate as raw exceptions.

**Why it's wrong:** If errors crossed the graph boundary silently, the caller wouldn't know whether a tool succeeded or failed, and would treat partial results as complete.

**Do this instead:** Always catch ToolError in tool_call node (`backend/app/graph/nodes.py` lines ~120–150), log to trace_events, and return result with last_failure set. Let decide_next inspect last_failure to decide retry/replan/give-up, not the caller.

### Provider Hardcoding

**What happens:** LLM provider is selected at LangGraph node construction time (via dependency injection), not at call time.

**Why it's wrong:** If provider was chosen at call time, every caller would need to know about fallback logic, and swapping providers would require touching multiple files.

**Do this instead:** Inject a single LLMProvider at graph-build time (see `dependencies.py:get_llm_provider`). If that provider is a FailoverProvider (which it should be in production), the fallback is transparent to the graph.

### Untraced State Mutations

**What happens:** Graph nodes return dict partials; StateGraph merges them into the full state. If a node modifies state without returning it, the change is lost.

**Why it's wrong:** Debug traces won't show state changes that happened silently; state becomes unpredictable across retries/checkpoints.

**Do this instead:** Nodes always return a dict with the fields they mutate (see `nodes.py:planner_node`, `observe_node`). StateGraph merges it, making every mutation visible.

## Error Handling

**Strategy:** Errors are caught at component boundaries and either logged (non-recoverable) or fed back into the graph for retry/replan logic.

**Patterns:**
- **Tool errors:** Caught in tool_call node, logged as trace event with last_failure, decide_next decides retry/replan
- **LLM provider errors:** Caught by FailoverProvider, fallback attempted transparently
- **Database errors:** Caught at session_runner level, entire session marked 'failed' with crash message
- **API validation errors:** FastAPI raises HTTPException (400/404/409), client handles with detail field

## Cross-Cutting Concerns

**Logging:**
- Approach: Python stdlib logging with structlog (not for structured fields here, just for namespacing)
- Pattern: logger = logging.getLogger("agent_ops.{module}"); logger.exception() on errors
- Captured in: stdout/stderr for Render deployment; visible in server logs

**Validation:**
- Approach: Pydantic models for API schemas, graph state type, LLMResponse, ToolCallRequest
- Pattern: Request bodies validated by FastAPI; graph state enforced by TypedDict; tool args validated by tool's args_schema
- Invalid data: FastAPI returns 422 Unprocessable Entity; graph state type mismatch raises TypeError at node execution

**Authentication:**
- Approach: Backend holds all secrets (API keys); frontend never sees them
- Pattern: Frontend talks only to own backend over HTTP; secrets live in .env (local) or environment (Render/Vercel)
- Secrets never: in bundle, in git, in logs, in error messages

**Rate Limiting:**
- Approach: Per-session tool-call cap (MAX_TOOL_CALLS) and per-step retry cap (MAX_STEP_RETRIES), per-plan replan cap (MAX_REPLANS)
- Pattern: Checked in decide_next_node; if exceeded, next_action = "give_up"
- Limits: Defined in `backend/app/graph/limits.py`

---

*Architecture analysis: 2026-08-25*
