# Testing Patterns

**Analysis Date:** 2026-08-25

## Test Framework

**Frontend:**
- Runner: Vitest 4.1.11
- Config: `frontend/vite.config.ts` with `test` block
- Environment: `jsdom` (browser DOM simulation)
- Setup file: `frontend/src/setupTests.ts` imports `@testing-library/jest-dom/vitest`
- Assertion library: Vitest built-in `expect` + Testing Library matchers

**Backend:**
- Runner: pytest (via `pyproject.toml` config)
- Config: `backend/pyproject.toml` `[tool.pytest.ini_options]`
- Test paths: `backend/tests/`
- Python path: `.` (backend directory is importable)
- Async mode: `asyncio_mode = "auto"`
- No fixtures for database tests read from real `.env` (ADR-014, ADR-017)

**Run Commands:**
```bash
# Frontend
npm test                # Run all tests once
npm run test:watch     # Watch mode (re-run on changes)
npm run test:coverage  # Generate coverage report

# Backend
pytest                 # Run all tests
pytest -v              # Verbose output
pytest tests/test_config.py  # Run specific file
pytest -k "openrouter" # Run tests matching pattern
```

## Test File Organization

**Location:**
- Frontend: Co-located with source files (same directory, same name with `.test.tsx` or `.test.ts` suffix)
  - Example: `src/lib/api.ts` → `src/lib/api.test.ts`
  - Example: `src/components/StatusBadge.tsx` → `src/components/StatusBadge.test.tsx`
- Backend: Centralized in `tests/` directory
  - Pattern: `tests/test_*.py` for each module or logical group
  - Examples: `test_config.py`, `test_graph_decide_next.py`, `test_tools_calculator.py`

**Naming:**
- Frontend: `SomeName.test.tsx` or `utility.test.ts`
- Backend: `test_module_name.py` (leading `test_` required by pytest auto-discovery)

**Structure:**
```
frontend/
├── src/
│   ├── lib/
│   │   ├── api.ts
│   │   └── api.test.ts          # Co-located
│   └── components/
│       ├── StatusBadge.tsx
│       └── StatusBadge.test.tsx  # Co-located

backend/
├── app/
│   ├── config.py
│   └── ...
└── tests/
    ├── conftest.py              # Shared fixtures
    ├── test_config.py           # Tests for app/config.py
    ├── test_integration_session.py
    └── ...
```

## Test Structure

**Suite Organization:**
```typescript
// Frontend pattern (Vitest + Testing Library)
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { StatusBadge } from './StatusBadge'

describe('StatusBadge', () => {
  // Optional: beforeEach/afterEach for setup/teardown
  beforeEach(() => {
    // Setup here
  })

  it('renders created status as "New"', () => {
    render(<StatusBadge status="created" />)
    expect(screen.getByText('New')).toBeInTheDocument()
  })
})
```

```python
# Backend pattern (pytest)
import pytest
from app.config import Settings

def test_cors_origin_list_splits_and_trims():
    """Docstring explains what's being tested."""
    settings = Settings(_env_file=None, cors_origins="http://localhost:5173, https://example.com")
    assert settings.cors_origin_list == ["http://localhost:5173", "https://example.com"]

def test_settings_construction_rejects_key_without_model(monkeypatch):
    """Tests use fixtures from conftest.py (e.g., monkeypatch)."""
    isolate_settings_env(monkeypatch)
    with pytest.raises(ValidationError, match="OPENROUTER_API_KEY and OPENROUTER_MODEL"):
        Settings(_env_file=None, openrouter_api_key="k", openrouter_model="")
```

**Patterns:**
- Setup: `beforeEach()` (frontend) or `@pytest.fixture` (backend) for test initialization
- Teardown: `afterEach()` (frontend) or fixture cleanup via `yield` (backend)
- Assertion: `expect()` (frontend) or `assert` (backend)

## Mocking

**Frontend Framework:** `vi` from Vitest

**Patterns:**
```typescript
// Global stubs (cleanup required)
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})
afterEach(() => {
  vi.unstubAllGlobals()
})

// Function mocks with assertions
(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
  ok: true,
  json: async () => ({ id: 's1', status: 'created' }),
})
expect(fetch).toHaveBeenCalledWith(url, expect.objectContaining({ method: 'POST' }))

// Access mock call details
const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
```

**Backend Framework:** unittest.mock (via pytest integration) or dependency injection

**Patterns:**
- No mocking of database in integration tests — use real Supabase Postgres (ADR-014)
- Mocking is reserved for LLM providers (real calls too slow/expensive for unit tests)
- Custom fake implementations for testing (e.g., `_ScriptedLLM` in `test_integration_session.py`)
- Dependency override pattern: Tests use `app.dependency_overrides` to inject mock implementations

**What to Mock:**
- HTTP calls (fetch in frontend)
- Expensive external calls (LLM providers)
- Non-deterministic behavior (crypto, dates)

**What NOT to Mock:**
- Database calls in integration tests (test real persistence)
- Framework internals (FastAPI, React, pytest)
- Application business logic — test the real implementation

## Fixtures and Factories

**Frontend Test Data:**
```typescript
// Parametrized tests using it.each
const cases: [SessionStatus, string][] = [
  ['created', 'New'],
  ['running', 'Running'],
  ['awaiting_approval', 'Needs approval'],
  ['done', 'Done'],
  ['failed', 'Failed'],
]

it.each(cases)('renders %s as "%s"', (status, label) => {
  render(<StatusBadge status={status} />)
  expect(screen.getByText(label)).toBeInTheDocument()
})
```

**Backend Test Fixtures** (from `tests/conftest.py`):
```python
@pytest.fixture
def make_client(monkeypatch):
  """Factory fixture: build a TestClient with custom Settings."""
  isolate_settings_env(monkeypatch)
  
  def _make_client(**settings_overrides) -> TestClient:
    settings = Settings(_env_file=None, **settings_overrides)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)
  
  yield _make_client
  app.dependency_overrides.clear()

@pytest.fixture
def client(make_client) -> TestClient:
  """Default client with no configuration."""
  return make_client()

@pytest.fixture(scope="session")
def db_pool():
  """Real database pool (reads real DATABASE_URL from .env)."""
  settings = Settings()  # Not _env_file=None — deliberate
  if not settings.database_url:
    pytest.skip("DATABASE_URL not configured")
  pool = ConnectionPool(conninfo=settings.database_url, ...)
  yield pool
  pool.close()
```

**Test Data Strategy:**
- No test data files (JSON, YAML); inline test data in test functions
- Minimal data: Only include fields required for the specific test
- Database: Real rows created via `repo` module and deleted in fixture cleanup

## Coverage

**Requirements:** Not formally enforced; tests rely on review
- Backend: Emphasis on integration and graph logic coverage (real database tests in ADR-014)
- Frontend: Component behavior and API error handling

**View Coverage:**
```bash
# Frontend
npm run test:coverage
# Generates coverage/ directory; open coverage/index.html in browser

# Backend
pytest --cov=app --cov-report=html
# Or add to pytest.ini if coverage desired
```

## Test Types

**Frontend Unit Tests:**
- Scope: Individual components and utility functions
- Approach: Render component, assert rendered output
- Example: `StatusBadge.test.tsx` tests all status variants
- Use Testing Library queries (`getByText`, `getByRole`) for real user interactions

**Frontend Integration Tests:**
- Not yet implemented; current suite is unit-focused
- Future: Route navigation, multi-component flows, API integration

**Backend Unit Tests:**
- Scope: Configuration parsing, error taxonomy, graph logic
- Approach: Direct function calls with test data
- Example: `test_config.py` validates `Settings` construction and properties
- Example: `test_graph_decide_next.py` tests decision logic independent of LLM calls

**Backend Integration Tests:**
- Scope: Full request path through FastAPI app with real database
- Approach: `TestClient` + real database fixtures
- Example: `test_integration_session.py` creates sessions, sends messages, checks persistence
- Database: Real Supabase Postgres connection, rows cleaned up after test

**Backend DB-Backed Tests:**
- Require `DATABASE_URL` in `.env` or CI secrets (ADR-014)
- Skip gracefully if not configured: `pytest.skip("DATABASE_URL not configured")`
- Cleanup: Fixtures use `db_pool` with explicit `DELETE` statements
- Isolation: Each test uses dedicated database transaction when possible

## Common Patterns

**Async Testing:**
```python
# Backend async tests (pytest asyncio_mode="auto")
async def test_session_runner_handles_approval_pause(db_pool):
  # pytest automatically runs async test functions with asyncio
  result = await session_runner(state, ...)
  assert result["status"] == "awaiting_approval"
```

```typescript
// Frontend async tests
it('resolves with the parsed JSON body on 2xx response', async () => {
  (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: true,
    json: async () => session,
  })
  await expect(createSession()).resolves.toEqual(session)
})
```

**Error Testing:**
```typescript
// Frontend: Expect custom error class
it('throws an ApiError carrying the backend detail message', async () => {
  ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: false,
    status: 409,
    json: async () => ({ detail: "session is 'done'" }),
  })
  const error = await sendMessage('s1', 'hi').catch((e: unknown) => e)
  expect(error).toBeInstanceOf(ApiError)
  expect((error as ApiError).status).toBe(409)
})
```

```python
# Backend: Expect specific exception with message pattern
def test_settings_construction_rejects_key_without_model(monkeypatch):
  isolate_settings_env(monkeypatch)
  with pytest.raises(ValidationError, match="OPENROUTER_API_KEY and OPENROUTER_MODEL"):
    Settings(_env_file=None, openrouter_api_key="k", openrouter_model="")
```

**Mocking Multiple Calls:**
```typescript
// Track multiple calls in sequence
;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({}) })
await rejectPendingAction('p1')
await rejectPendingAction('p1', 'not needed')
const [, init1] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
const [, init2] = (fetch as ReturnType<typeof vi.fn>).mock.calls[1]
expect(JSON.parse(init1.body)).toEqual({ reason: null })
expect(JSON.parse(init2.body)).toEqual({ reason: 'not needed' })
```

**Database Test Cleanup:**
```python
# Fixtures auto-cleanup with context managers
with db_pool.connection() as conn:
  conn.execute("DELETE FROM sessions WHERE id = %s", (row["id"],))
```

## Special Considerations

**Environment Isolation (ADR-017):**
- All unit tests use `Settings(_env_file=None, ...)` to avoid reading developer's real `.env`
- Integration tests need real `DATABASE_URL` so they deliberately read `.env`
- Use `isolate_settings_env(monkeypatch)` to clear OS environment variables during tests
- CI: Real secrets injected as environment variables; tests still use `_env_file=None` to verify file loading doesn't interfere

**Pre-Commit Hooks:**
- Run via `.pre-commit-config.yaml` before commit
- Frontend: `npm run lint` (ESLint) and `npm run format:check` (Prettier)
- Backend: `ruff check .` (Ruff) and `black --check .` (Black)
- Setup: `pre-commit install` (once per repository)

---

*Testing analysis: 2026-08-25*
