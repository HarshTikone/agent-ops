# Codebase Structure

**Analysis Date:** 2026-08-25

## Directory Layout

```
agent-ops/
├── backend/                        # FastAPI application (Python)
│   ├── app/
│   │   ├── api/                   # HTTP routers (CRUD endpoints)
│   │   │   ├── sessions.py        # POST/GET sessions, messages, trace
│   │   │   ├── approvals.py       # POST approve/reject
│   │   │   ├── health.py          # GET /health/ready readiness checks
│   │   │   ├── schemas.py         # Pydantic request/response models
│   │   │   └── __init__.py
│   │   ├── graph/                 # LangGraph state machine
│   │   │   ├── build.py           # Wire nodes into compiled graph
│   │   │   ├── nodes.py           # Node implementations (planner, tool_call, etc.)
│   │   │   ├── state.py           # GraphState TypedDict definition
│   │   │   ├── limits.py          # MAX_TOOL_CALLS, MAX_REPLANS, MAX_STEP_RETRIES
│   │   │   ├── serde.py           # Serialization helpers
│   │   │   └── __init__.py
│   │   ├── llm/                   # LLM provider abstraction
│   │   │   ├── base.py            # LLMProvider protocol, LLMResponse, ToolCallRequest
│   │   │   ├── gemini.py          # GeminiProvider implementation
│   │   │   ├── openrouter.py      # OpenRouterProvider implementation
│   │   │   ├── failover.py        # FailoverProvider (Gemini → OpenRouter)
│   │   │   ├── errors.py          # LLM-specific exceptions
│   │   │   └── __init__.py
│   │   ├── tools/                 # Tool adapters
│   │   │   ├── base.py            # Tool protocol (name, description, args_schema, run)
│   │   │   ├── registry.py        # build_tool_registry, to_langchain_tools
│   │   │   ├── calculator.py      # CalculatorTool (arithmetic evaluation)
│   │   │   ├── notes_store.py     # NotesStoreTool (key-value read/write)
│   │   │   ├── web_search.py      # WebSearchTool (Tavily API)
│   │   │   ├── errors.py          # ToolError exception
│   │   │   └── __init__.py
│   │   ├── main.py                # FastAPI app setup, router includes
│   │   ├── config.py              # Settings (pydantic-settings from .env)
│   │   ├── dependencies.py        # Dependency injection factories
│   │   ├── db.py                  # Database connection pool, checkpointer factory
│   │   ├── repository.py          # CRUD functions (repo.*)
│   │   └── session_runner.py      # Bridge graph execution to database
│   ├── migrations/                # Alembic SQL migrations (or raw .sql)
│   │   └── 0001_initial_schema.sql
│   ├── tests/                     # pytest test suite
│   │   ├── test_*.py              # Unit tests (one per module)
│   │   └── conftest.py            # pytest fixtures (pool, checkpointer, etc.)
│   ├── scripts/                   # Utility scripts (one-offs, not part of app)
│   ├── Dockerfile                 # Multi-stage Docker build
│   ├── pyproject.toml             # Project metadata (optional, see below)
│   ├── requirements.txt           # Pinned dependencies (pip)
│   ├── requirements-dev.txt       # Dev-only (pytest, ruff, etc.)
│   ├── .dockerignore              # Docker build exclusions
│   └── .venv/                     # Python virtual environment (git-ignored)
│
├── frontend/                       # React + TypeScript (Vite)
│   ├── src/
│   │   ├── components/            # Reusable UI components
│   │   │   ├── ChatPanel.tsx      # Task input form or transcript display
│   │   │   ├── ApprovalModal.tsx  # Human approval interaction
│   │   │   ├── TraceViewer.tsx    # Renders trace_events (node decisions)
│   │   │   ├── StatusBadge.tsx    # Session status indicator
│   │   │   ├── BackendStatus.tsx  # Readiness status in header
│   │   │   └── *.test.tsx         # Component tests (co-located)
│   │   ├── pages/                 # Route-level pages
│   │   │   ├── SessionListPage.tsx      # "/" — list all sessions
│   │   │   ├── SessionPage.tsx          # "/sessions/:sessionId" — single session view
│   │   │   └── *.test.tsx               # Page tests
│   │   ├── lib/                   # Shared utilities
│   │   │   ├── api.ts             # Fetch wrappers, API types (Session, TraceEvent, etc.)
│   │   │   ├── api.test.ts        # API function mocking tests
│   │   │   └── (other utilities as needed)
│   │   ├── App.tsx                # Router setup and layout
│   │   ├── App.test.tsx           # App integration tests
│   │   ├── main.tsx               # React entry point (ReactDOM.createRoot)
│   │   └── setupTests.ts          # vitest configuration (JSDOM, globals)
│   ├── public/                    # Static assets (favicon, etc.)
│   ├── dist/                      # Built output (Vite; git-ignored)
│   ├── node_modules/              # Dependencies (git-ignored)
│   ├── index.html                 # HTML template (Vite entry point)
│   ├── Dockerfile                 # Docker build + nginx serving
│   ├── nginx.conf                 # nginx config (reverse proxy to backend)
│   ├── vite.config.ts             # Vite bundler configuration
│   ├── tsconfig.json              # TypeScript base config
│   ├── tsconfig.app.json          # TypeScript app config (extends base)
│   ├── tsconfig.node.json         # TypeScript build tools config
│   ├── eslint.config.js           # ESLint rules
│   ├── .prettierrc.json           # Prettier formatting
│   ├── package.json               # npm dependencies
│   ├── package-lock.json          # Pinned npm versions
│   ├── README.md                  # Frontend-specific setup
│   ├── .dockerignore              # Docker build exclusions
│   ├── .env                       # Local dev config (git-ignored)
│   ├── .env.example               # Template for .env
│   └── .gitignore                 # Git exclusions
│
├── .planning/                      # GSD planning documents (generated)
│   └── codebase/
│       ├── ARCHITECTURE.md        # This document (layer, pattern, data flow)
│       └── STRUCTURE.md           # Directory layout, naming, where to add code
│
├── .claude/                        # Claude Code config
│   ├── skills/                    # Project-specific skills (if any)
│   └── settings.json              # Claude Code settings
│
├── .github/                        # GitHub-specific config
│   ├── workflows/                 # CI/CD pipelines (GitHub Actions)
│   ├── ISSUE_TEMPLATE/            # Issue templates
│   └── pull_request_template.md
│
├── ARCHITECTURE.md                # Project's own architecture documentation
├── ADR.md                         # Architecture Decision Records
├── README.md                      # Root-level setup guide
├── LICENSE                        # Apache 2.0
├── .env                           # Secrets (git-ignored)
├── .env.example                   # Template for .env
├── .gitignore                     # Git exclusions
├── .pre-commit-config.yaml        # Pre-commit hooks (ruff, prettier)
└── MASTER_PROMPT.md               # Project's context for AI agents
```

## Directory Purposes

**backend/app/api/:**
- Purpose: FastAPI routers that handle HTTP requests
- Contains: Router definitions, endpoint handlers, request/response validation
- Key files: `sessions.py` (main CRUD + session execution), `approvals.py` (approve/reject), `health.py` (readiness)

**backend/app/graph/:**
- Purpose: LangGraph graph construction and node implementations
- Contains: State definition, node logic, routing decisions, interrupts
- Key files: `state.py` (GraphState), `nodes.py` (node implementations), `build.py` (graph assembly)

**backend/app/llm/:**
- Purpose: LLM provider abstraction and concrete implementations
- Contains: Protocol definition, Gemini adapter, OpenRouter adapter, failover logic
- Key files: `base.py` (protocol), `failover.py` (automatic fallback), `gemini.py`, `openrouter.py`

**backend/app/tools/:**
- Purpose: Tool adapters for agent use
- Contains: Tool protocol, concrete tools (calculator, notes, web search), registry
- Key files: `base.py` (protocol), `registry.py` (factory), individual tool files

**backend/tests/:**
- Purpose: Unit and integration tests for backend
- Contains: Test fixtures, mocked providers, graph execution tests
- Pattern: One test file per module (test_config.py, test_graph_nodes.py, test_tools_calculator.py, etc.)

**frontend/src/components/:**
- Purpose: Reusable React components
- Contains: Presentational and container components for chat, trace, approval
- Pattern: Each component is a `.tsx` file with a co-located `.test.tsx` file

**frontend/src/pages/:**
- Purpose: Route-level pages (full-screen views)
- Contains: SessionListPage (/), SessionPage (/sessions/:id)
- Pattern: Page component manages data fetching, state, and passes data to child components

**frontend/src/lib/:**
- Purpose: Shared utilities and API client
- Contains: Fetch wrappers, API types, helper functions
- Key files: `api.ts` (API client functions + types)

## Key File Locations

**Entry Points:**
- Backend HTTP: `backend/app/main.py` (FastAPI app, startup)
- Backend graph execution: `backend/app/session_runner.py` (invokes compiled graph)
- Frontend: `frontend/src/main.tsx` (React DOM render), `frontend/src/App.tsx` (router)

**Configuration:**
- Backend settings: `backend/app/config.py` (pydantic-settings from .env)
- Backend dependencies: `backend/app/dependencies.py` (get_llm_provider, get_db_pool, get_checkpointer)
- Backend database: `backend/app/db.py` (connection pool, checkpointer factory)
- Frontend API config: `frontend/src/lib/api.ts` (API_BASE_URL, types)

**Core Logic:**
- Graph orchestration: `backend/app/graph/build.py`, `backend/app/graph/nodes.py`
- Session execution: `backend/app/session_runner.py`
- Database CRUD: `backend/app/repository.py`
- Tool coordination: `backend/app/tools/registry.py`
- LLM abstraction: `backend/app/llm/base.py`, `backend/app/llm/failover.py`

**Testing:**
- Backend fixtures: `backend/tests/conftest.py` (pool, checkpointer mocks)
- Frontend setup: `frontend/src/setupTests.ts` (JSDOM, test utilities)

## Naming Conventions

**Files:**
- Python: snake_case (repository.py, session_runner.py, get_db_pool)
- TypeScript/React: PascalCase for components (ChatPanel.tsx), camelCase for utilities (api.ts)
- Tests: test_*.py (pytest), *.test.tsx (vitest)

**Directories:**
- Plural for collections of related modules (tools/, components/, pages/)
- Descriptive, domain-focused (graph/, llm/, api/)

**Functions:**
- Backend: snake_case, verb prefixes (create_session, send_message, start_session_run)
- Frontend: camelCase, verb prefixes (sendMessage, approvePendingAction, fetchReadiness)

**Types/Interfaces:**
- Python: PascalCase (GraphState, LLMResponse, ToolCallRequest, ToolError)
- TypeScript: PascalCase (Session, TraceEvent, SessionStatus, ReadinessResponse)

**Constants:**
- Backend: UPPER_SNAKE_CASE (MAX_TOOL_CALLS, IRREVERSIBLE_STEPS, PLANNER_SYSTEM_PROMPT)
- Frontend: UPPER_SNAKE_CASE (API_BASE_URL)

## Where to Add New Code

**New Feature (e.g., a new tool):**
- **Implementation:**
  - Create tool class in `backend/app/tools/{tool_name}.py`
  - Implement Tool protocol (name, description, args_schema, run)
  - Add tool to registry factory in `backend/app/tools/registry.py`
- **Tests:**
  - Add `backend/tests/test_tools_{tool_name}.py`
  - Mock external dependencies, test run() with success/failure paths
- **Graph integration:**
  - Add tool to langchain_tools list in `registry.to_langchain_tools`
  - If tool requires approval (irreversible action), add to IRREVERSIBLE_STEPS in `backend/app/graph/nodes.py`

**New API Endpoint:**
- **Location:** `backend/app/api/{router_name}.py`
- **Pattern:** Define Pydantic request/response models in `backend/app/api/schemas.py`, implement handler in router file
- **Dependencies:** Inject via Depends() (pool, checkpointer, llm, settings)
- **Include router:** In `backend/app/main.py` via `app.include_router`
- **Test:** Add to `backend/tests/test_api_*.py`

**New Graph Node:**
- **Location:** Implement logic in `backend/app/graph/nodes.py` or as a factory function
- **Pattern:** Node function takes GraphState, returns dict of mutations
- **Wire:** Add to graph in `backend/app/graph/build.py` via `graph.add_node` and edges
- **Test:** Add to `backend/tests/test_graph_nodes.py` or `test_graph_decide_next.py`

**New UI Component:**
- **Location:** `frontend/src/components/{ComponentName}.tsx`
- **Pattern:** Export default function (functional component), type props as interface
- **Test:** Co-located `frontend/src/components/{ComponentName}.test.tsx`
- **Example:** See `ChatPanel.tsx` for component taking session + callbacks

**New Frontend Page:**
- **Location:** `frontend/src/pages/{PageName}.tsx`
- **Pattern:** Full-screen view, manages data fetching with useEffect, renders sub-components
- **Routing:** Import in `frontend/src/App.tsx`, add Route element
- **Test:** Co-located `frontend/src/pages/{PageName}.test.tsx`

**New Database Query:**
- **Location:** Add function to `backend/app/repository.py`
- **Pattern:** Function takes pool and returns result dict or None
- **Safety:** No ORM — write raw SQL with bound parameters
- **Usage:** Call from API handlers or session_runner, never from graph nodes directly

**New Configuration Variable:**
- **Backend:** Add field to Settings class in `backend/app/config.py`, document in `backend/.env.example`
- **Frontend:** Add to .env.example in `frontend/`, access via import.meta.env.VITE_* in code

## Special Directories

**backend/migrations/:**
- Purpose: Database schema changes (SQL or Alembic)
- Generated: No (hand-written SQL)
- Committed: Yes
- Pattern: One file per schema version (0001_initial_schema.sql, 0002_add_*.sql, etc.)

**backend/.venv/:**
- Purpose: Python virtual environment
- Generated: Yes (python -m venv .venv)
- Committed: No (.gitignored)
- Pattern: Activated before running uvicorn or pytest

**frontend/dist/:**
- Purpose: Built frontend bundle
- Generated: Yes (npm run build)
- Committed: No (.gitignored)
- Pattern: Output of Vite build; served by nginx in Docker

**frontend/node_modules/:**
- Purpose: npm installed packages
- Generated: Yes (npm install)
- Committed: No (.gitignored)
- Pattern: Lock file (package-lock.json) is committed, node_modules is not

**backend/.ruff_cache/ and frontend/.eslint-cache/:**
- Purpose: Linter caches (speed up repeat runs)
- Generated: Yes
- Committed: No (.gitignored)

**.env files (root + frontend):**
- Purpose: Environment variables for secrets and configuration
- Generated: No (copied from .env.example)
- Committed: No (.gitignored)
- Pattern: .env.example is committed as template; .env is git-ignored

**.planning/codebase/:**
- Purpose: GSD (Goal, Schedule, Decide) analysis documents
- Generated: Yes (by /gsd-map-codebase)
- Committed: Yes
- Pattern: ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md, CONCERNS.md (as applicable)

---

*Structure analysis: 2026-08-25*
