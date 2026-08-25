# Technology Stack

**Analysis Date:** 2026-08-25

## Languages

**Primary:**
- TypeScript (v6.0) - Frontend application source (`frontend/src/**/*.tsx`)
- Python (v3.11) - Backend API and agent services (`backend/app/**/*.py`)

**Build/Configuration:**
- JavaScript (Node.js) - Package manifest, build tools, configuration

## Runtime

**Environment:**
- Node.js 22 (frontend) - Specified in CI workflow `.github/workflows/ci.yml`
- Python 3.11 (backend) - Specified in `backend/pyproject.toml` and CI workflow
- ASGI server via Uvicorn (`uvicorn[standard]==0.52.4`)

**Package Manager:**
- npm - Manages frontend dependencies via `frontend/package.json`
- pip - Manages Python dependencies via `backend/requirements.txt`
- Lockfiles: `frontend/package-lock.json` (present), `backend/` uses `requirements.txt` (pinned)

## Frameworks

**Core:**
- FastAPI 0.141.1 - REST API server, dependency injection (`backend/app/main.py`)
- React 19.2.8 - UI framework (`frontend/src/App.tsx`)
- React Router DOM 7.18.2 - Client-side routing (`frontend/src/`)

**Testing:**
- pytest - Python backend testing (`backend/tests/`)
- Vitest 4.1.11 - TypeScript/JavaScript testing (`frontend/src/**/*.test.tsx`)
- @testing-library/react 16.3.2 - Component testing utilities

**Build/Dev:**
- Vite 8.2.0 - JavaScript bundler and dev server (`frontend/vite.config.ts`)
- @vitejs/plugin-react 6.0.4 - React JSX support
- @tailwindcss/vite 4.3.3 - Tailwind CSS integration
- TypeScript ~6.0.2 - Type checking (frontend)
- Black 0.141.1 - Python code formatter
- Ruff - Python linter
- ESLint 10.9.0 - JavaScript/TypeScript linter (`frontend/eslint.config.js`)
- Prettier 3.9.6 - JavaScript/TypeScript formatter (`frontend/.prettierrc.json`)

## Key Dependencies

**Critical:**

**LLM & Agent Orchestration:**
- langgraph 1.2.11 - Agent graph orchestration, state management, interrupts (`backend/app/graph/`)
- langchain-google-genai 4.3.5 - Primary LLM provider (Gemini) (`backend/app/llm/gemini.py`)
- langchain-openai 1.6.0 - Fallback LLM provider (OpenRouter) (`backend/app/llm/openrouter.py`)
- openai 3.3.1 - OpenAI SDK dependency (used by langchain-openai)
- langchain-core - Shared interfaces for LLM operations

**Database & State Persistence:**
- psycopg[binary] 3.3.4 - PostgreSQL driver with binary extensions
- psycopg-pool 3.3.1 - Connection pooling for PostgreSQL
- langgraph-checkpoint-postgres 3.1.2 - Graph state checkpoint storage (`backend/app/db.py`)

**Web & HTTP:**
- httpx 0.28.1 - Async HTTP client for Tavily web search (`backend/app/tools/web_search.py`)
- Starlette - ASGI framework (FastAPI dependency)

**Configuration & Validation:**
- pydantic 2.13.4 - Data validation (`backend/app/config.py`)
- pydantic-settings 2.15.0 - Environment-based settings
- python-dotenv 1.2.3 - .env file loading

**Observability & Quality:**
- structlog 26.1.0 - Structured logging (`backend/app/`)
- slowapi 0.1.10 - Rate limiting middleware
- tenacity 9.1.4 - Retry logic for transient failures

**Testing Utilities (Frontend):**
- @testing-library/jest-dom 7.0.1 - DOM matchers
- @testing-library/user-event 14.6.6 - User interaction simulation
- jsdom 30.0.1 - DOM implementation for Node.js tests
- @vitest/coverage-v8 4.1.11 - Coverage reporting

**Type Safety (Frontend):**
- @types/react 19.2.17 - React type definitions
- @types/react-dom 19.2.3 - React DOM type definitions
- @types/node 24.13.3 - Node.js type definitions

## Configuration

**Environment:**
- Configuration loaded from `.env` at repo root → read by `backend/app/config.py`
- pydantic-settings handles environment variable resolution
- Settings singleton pattern via `@lru_cache` on `get_settings()`
- Key configuration files:
  - `.env` (repository root) - Environment variables
  - `backend/app/config.py` - Centralized settings with validation
  - `frontend/.prettierrc.json` - Formatting rules
  - `frontend/eslint.config.js` - Linting rules
  - `frontend/tsconfig.json` - TypeScript compiler options

**Build:**
- Frontend: `frontend/vite.config.ts` - Vite build config with React and Tailwind plugins
- Backend: `backend/pyproject.toml` - Ruff, Black, and pytest configuration
- Pre-commit hooks: `.pre-commit-config.yaml` - Local linting/formatting enforcement

**Environment Variables Required:**
- `GEMINI_API_KEY` - Google Gemini API key (primary LLM)
- `GEMINI_MODEL` - Gemini model identifier (default: "gemini-3.1-flash-lite")
- `OPENROUTER_API_KEY` - OpenRouter fallback key (optional if not using fallback)
- `OPENROUTER_MODEL` - OpenRouter model identifier (must match with API key, both-or-none)
- `TAVILY_API_KEY` - Tavily web search API key
- `DATABASE_URL` - PostgreSQL connection string (raw psycopg connection)
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_SECRET_KEY` - Supabase service role key
- `CORS_ORIGINS` - Comma-separated list of allowed origins (default: "http://localhost:5173")
- `ENVIRONMENT` - "development" or "production"
- `LOG_LEVEL` - "debug", "info", "warning", or "error"

## Platform Requirements

**Development:**
- Python 3.11+ with venv
- Node.js 22+ with npm
- PostgreSQL 12+ (local or remote via DATABASE_URL)
- git and pre-commit for hooks
- pip and npm for dependency management

**Production:**
- Python 3.11+ runtime
- Node.js 22+ for frontend build (build-time only; frontend is static HTML/CSS/JS)
- PostgreSQL 12+ database
- ASGI-compatible hosting (Render, Railway, Heroku, AWS Lambda via adapter)
- Static file hosting for frontend build output

---

*Stack analysis: 2026-08-25*
