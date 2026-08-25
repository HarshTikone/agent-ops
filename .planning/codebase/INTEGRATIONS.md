# External Integrations

**Analysis Date:** 2026-08-25

## APIs & External Services

**LLM Providers:**

**Google Gemini (Primary):**
- Service: Google Generative AI (Gemini models)
- What it's used for: Primary LLM provider for agent planning and tool selection
- SDK/Client: `langchain-google-genai==4.3.5`
- Auth: `GEMINI_API_KEY` environment variable
- Model: Configurable via `GEMINI_MODEL` env var (default: "gemini-3.1-flash-lite")
- Implementation: `backend/app/llm/gemini.py` wraps `ChatGoogleGenerativeAI`
- Error handling: Normalizes rate limits (`ModelRateLimitError`), server errors (`ModelAPIError`), and timeouts (`httpx.TimeoutException`/`httpx.ConnectError`) to project's custom exception types
- Timeout: 30 seconds per request

**OpenRouter (Fallback):**
- Service: OpenRouter (OpenAI-compatible proxy for multiple models)
- What it's used for: Fallback LLM provider when Gemini is rate-limited or unavailable
- SDK/Client: `langchain-openai==1.6.0` with `base_url=https://openrouter.ai/api/v1`
- Auth: `OPENROUTER_API_KEY` environment variable
- Model: Configurable via `OPENROUTER_MODEL` env var (must be set with key or both empty)
- Implementation: `backend/app/llm/openrouter.py` wraps `ChatOpenAI` with custom base URL
- Error handling: Normalizes all transient failures to LangChain standard types (`ModelRateLimitError`, `ModelAPIError`, `ModelTimeoutError`, `ModelConnectionError`)
- Timeout: 30 seconds per request
- Validation: ADR-020 enforces both API key and model must be set or both empty (half-configured fails at startup)

**Web Search:**
- Service: Tavily Search API
- What it's used for: Real-time web search tool for agents to find current information
- Implementation: `backend/app/tools/web_search.py` makes raw HTTP POST requests
- Auth: `TAVILY_API_KEY` environment variable, sent as Bearer token in Authorization header
- API Endpoint: `https://api.tavily.com/search`
- Request format: JSON with `query` and `max_results` (set to 5)
- Error handling: Distinguishes rate limits (429), server errors (5xx), and request errors (4xx)
- Timeout: 15 seconds per request
- Quota: Free tier = 1,000 credits/month, 100 requests/min (1 credit per basic search)

## Data Storage

**Databases:**

**PostgreSQL Primary Database:**
- Type: PostgreSQL 12+
- Connection: Via `DATABASE_URL` connection string (raw psycopg, no ORM)
- Client: `psycopg[binary]==3.3.4` (with C extension for performance)
- Connection pooling: `psycopg-pool==3.3.1` with max pool size of 5
- Pool configuration: `autocommit=True`, `dict_row` factory for result rows
- Initialization: `backend/app/db.py` manages pool singleton via `get_db_pool()`
- Tables created by:
  - Custom schema in `backend/app/repository.py` via raw SQL
  - LangGraph checkpoint tables auto-created by `PostgresSaver.setup()` (idempotent CREATE TABLE IF NOT EXISTS)

**Tables:**
- `sessions` - Agent session metadata (task, status, final_answer, timestamps)
- `messages` - Conversation messages per session (role, content)
- `trace_events` - Decision trace log (node, detail, provider, timing)
- `session_memory` - Session-scoped notes store (notes_store tool backend)
- `langgraph_checkpoint` - LangGraph state checkpoints for interrupts/resumption
- `langgraph_checkpoint_blobs` - Blob storage for checkpoint serialization

**File Storage:**
- Local filesystem only - Session data stored in PostgreSQL, not external blob storage

**Caching:**
- Python-level caching via `@lru_cache` decorators:
  - `get_settings()` in `backend/app/config.py` - Settings singleton
  - `get_db_pool()` in `backend/app/db.py` - Connection pool singleton
  - `get_checkpointer()` in `backend/app/db.py` - PostgresSaver singleton
- No external cache (Redis/Memcached)

## Authentication & Identity

**Auth Provider:**
- Custom - No third-party auth service
- Implementation: Stateless API with no user authentication layer
- All endpoints public (no API key requirement)
- Session isolation via UUID session IDs
- Approval decisions via session state (no user authentication needed)

**Credentials & Secrets:**
- All sensitive credentials in environment variables (`.env` file)
- Environment variables loaded by `pydantic-settings` in `backend/app/config.py`
- Critical vars protected in CI: `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `TAVILY_API_KEY`, `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`

## Monitoring & Observability

**Error Tracking:**
- None configured - No Sentry/DataDog/exception tracking service
- Backend logs exceptions via `logging` module and structlog
- Frontend errors logged to browser console only

**Logs:**
- Python backend: `logging` module + `structlog==26.1.0` for structured logging
- Log level: Configurable via `LOG_LEVEL` env var (default: "info")
- Logs to stdout (suitable for container platforms like Render)
- Frontend: Browser console only

**Tracing:**
- Request-level tracing via `trace_events` table in PostgreSQL
- Each agent decision step logged with node name, detail, provider, timestamp
- Graph execution history accessible via `GET /sessions/{session_id}/trace` endpoint

## CI/CD & Deployment

**Hosting:**
- Backend: ASGI-compatible platforms (Render, Railway, Heroku, AWS Lambda)
- Frontend: Static HTML/CSS/JS hosting (GitHub Pages, Vercel, Render static service)
- Database: External PostgreSQL (Render Postgres, AWS RDS, Supabase)

**CI Pipeline:**
- GitHub Actions (`.github/workflows/ci.yml`)
- Runs on push to main and all pull requests
- Backend job: Python 3.11 setup, pip install, ruff lint, black format check, pytest
- Frontend job: Node 22 setup, npm ci, eslint lint, prettier format check, vitest test, build
- Uses GitHub Secrets for sensitive environment variables in test environment

**Pre-commit Hooks:**
- Local enforcement via `.pre-commit-config.yaml`
- Backend: ruff check, black format check
- Frontend: eslint, prettier format check
- Plus standard hooks: large files, merge conflicts, trailing whitespace, private keys

## Environment Configuration

**Required env vars (see `backend/app/config.py`):**
- `GEMINI_API_KEY` - API key for Google Gemini (required for operation)
- `GEMINI_MODEL` - Model identifier (defaults to "gemini-3.1-flash-lite")
- `OPENROUTER_API_KEY` - OpenRouter API key (optional fallback, must pair with model)
- `OPENROUTER_MODEL` - OpenRouter model ID (optional fallback, must pair with key)
- `TAVILY_API_KEY` - Tavily search API key (required for web_search tool)
- `DATABASE_URL` - PostgreSQL connection string (required)
- `SUPABASE_URL` - Supabase project URL (stored in config, not actively used per ADR-014)
- `SUPABASE_SECRET_KEY` - Supabase secret key (stored in config, not actively used per ADR-014)
- `CORS_ORIGINS` - Allowed CORS origins (defaults to "http://localhost:5173" for dev)
- `ENVIRONMENT` - "development" or "production" (defaults to "development")
- `LOG_LEVEL` - "debug", "info", "warning", or "error" (defaults to "info")

**Secrets location:**
- Local dev: `.env` file at repo root (git-ignored, listed in `.gitignore`)
- CI/CD: GitHub Secrets (`.github/workflows/ci.yml`)
- Production: Environment variables set by hosting platform's dashboard (Render, Vercel, etc.)

## Webhooks & Callbacks

**Incoming:**
- None configured - API is REST-only, no webhook listeners

**Outgoing:**
- None configured - No outbound webhooks to external services

**Request/Response Communication:**
- Backend API: REST/JSON via FastAPI
- Frontend API client: `frontend/src/lib/api.ts` uses `fetch()` for HTTP requests to `http://localhost:8000` (dev) or deployed backend URL (production)
- Session messages: Synchronous `POST /sessions/{session_id}/messages` blocks until graph pauses or completes
- Trace events: Asynchronous `GET /sessions/{session_id}/trace` fetches decision history

---

*Integration audit: 2026-08-25*
