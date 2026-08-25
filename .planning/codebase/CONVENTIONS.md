# Coding Conventions

**Analysis Date:** 2026-08-25

## Naming Patterns

**Files:**
- TypeScript/React files: `camelCase.ts` or `camelCase.tsx` for components and utilities
- Python files: `snake_case.py` for modules, functions, and variables
- Test files: `test_*.py` (Python) or `*.test.ts(x)` (TypeScript) — co-located next to source files
- Components: `PascalCase.tsx` (e.g., `StatusBadge.tsx`, `ChatPanel.tsx`)

**Functions:**
- TypeScript/JavaScript: `camelCase` for all functions and methods
- Python: `snake_case` for all functions and methods
- React components: `PascalCase` for component names (exported as default or named exports)
- Private functions: Prefix with underscore (e.g., `_needs_approval`, `_reject_half_configured_openrouter`)

**Variables:**
- TypeScript/JavaScript: `camelCase` for variables and constants; `SCREAMING_SNAKE_CASE` only for truly immutable globals
- Python: `snake_case` for variables; `ALL_CAPS` for module-level constants
- React state: `camelCase` (e.g., `draft`, `submitting`, `error`)
- UI class maps: `LABELS` and `COLORS` as constants mapping types to string values (e.g., `StatusBadge.tsx`)

**Types:**
- TypeScript interfaces: `PascalCase` (e.g., `ReadinessResponse`, `SessionStatus`, `Session`)
- Python type hints: Use union literals (e.g., `Literal["created", "running"]`) and generic types (e.g., `list[str]`)
- Type imports: Use `type` keyword when importing types only (e.g., `import type { SessionStatus } from '../lib/api'`)

## Code Style

**Formatting:**
- Frontend: Prettier with 100-char line width, single quotes, no semicolons, trailing commas
  - Config: `frontend/.prettierrc.json`
  - Run: `npm run format` to fix, `npm run format:check` to verify
- Backend: Black formatter with 100-char line width
  - Config: `backend/pyproject.toml`
  - Run: `black .` in backend directory

**Linting:**
- Frontend: ESLint with TypeScript support, React Hooks rules, React Refresh warnings
  - Config: `frontend/eslint.config.js`
  - Rules: `react-hooks/recommended`, `react-refresh/only-export-components` (warn)
  - Run: `npm run lint`
- Backend: Ruff with rules E, F, I (isort), UP, B (bugbear), SIM
  - Config: `backend/pyproject.toml`
  - Notable: `E501` (line length) ignored — handled by Black instead
  - FastAPI exceptions: `Depends()`, `Query()`, `Path()` calls in defaults are exempt from B008 mutable-default check
  - Run: `ruff check .` in backend directory

**TypeScript Strictness:**
- `tsconfig.app.json` enforces `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch`
- `verbatimModuleSyntax` requires explicit import/export syntax (no implicit from `type` exports)
- JSX: React 17+ auto-import, configured with `jsx: "react-jsx"` in `tsconfig.app.json`

## Import Organization

**Order:**
1. External/third-party imports (React, libraries, etc.)
2. Absolute imports from application (using aliases if configured)
3. Relative imports (e.g., `../lib/api`, `../components/StatusBadge`)

**Path Aliases:**
- Frontend: Uses relative paths; no configured aliases
- Backend: `app` is recognized as first-party via `isort` config in `pyproject.toml`

**Specific patterns:**
- React components import `type` separately: `import type { SessionStatus } from '../lib/api'`
- API functions export types alongside functions in same module (e.g., `api.ts` exports both `ApiError` class and `Session` interface)
- Python: Use `from __future__ import annotations` at the top for PEP 563 forward references

## Error Handling

**TypeScript/JavaScript:**
- Custom error classes extend `Error`: `class ApiError extends Error`
- Error properties set explicitly: `this.name = 'ApiError'`
- Catch with type narrowing: `(error as ApiError).status`
- Optional error recovery: Prefer early returns or throw over nested try-catch
- Fallback messages: Always provide generic message when detailed error parsing fails (see `api.ts` `request()` function)

**Python:**
- Error hierarchy: Base class `ProviderError`, then specific subclasses (`TransientProviderError`, `ProviderTimeoutError`, `ProviderRateLimitError`, `ProviderServerError`)
- Validation errors: Raise at class construction time (not at first use) for fast-fail startup behavior
- Use Pydantic's `model_validator` for cross-field validation (e.g., OpenRouter key/model must both be set or both empty)
- HTTP errors: FastAPI `HTTPException` with explicit `status_code` and `detail` message
- Tests: Expect specific exception types with `pytest.raises(ValidationError, match="pattern")`

**Common patterns:**
- Prefer exception handling over return codes
- Never silently ignore errors (no empty `except` or `pass`)
- Log at entry point if error is fatal, let caller decide if recoverable

## Logging

**Framework:**
- Python: `logging` module via `getLogger("module.name")` (e.g., `"agent_ops.api.sessions"`)
- TypeScript: No structured logging configured; would use console if needed

**Patterns:**
- Create logger once per module: `logger = logging.getLogger("agent_ops.graph")`
- Log startup/configuration issues at WARN level (e.g., "openrouter_not_configured: failover disabled")
- Use ADR references in log messages when referencing design decisions
- No logging of secrets or sensitive configuration values

## Comments

**When to Comment:**
- Implementation notes explaining "why" over "what" (docstrings at module/class/function level)
- Architectural decisions: Reference ADRs (e.g., "ADR-020: half-configured OpenRouter must fail at startup")
- Non-obvious behavior: Explain why a design choice exists (e.g., Record-typed status labels for exhaustiveness checking)
- Workarounds or hacks: Clearly mark with context for future removal

**JSDoc/TSDoc:**
- Frontend: Function docstrings use `/** ... */` style for exported functions
- Example from `api.ts`: Documents what `pending_action` field represents and when it's populated
- API routes: Docstrings explain synchronous/blocking behavior and why (e.g., "blocks until graph finishes or pauses")

**Python Docstrings:**
- Module-level: Explain purpose, dependencies, and design notes
- Class-level: Describe purpose and field relationships
- Function-level: Brief one-liner for simple functions; longer explanation for complex logic
- ADR references: Include when documenting non-obvious design (e.g., `_reject_half_configured_openrouter` references ADR-020)

## Function Design

**Size:** Prefer small, single-responsibility functions
- Python graph nodes: Typically 10-30 lines, one job per node
- TypeScript API helpers: ~20 lines each, focused on one endpoint/action
- React components: Logic extracted to hooks/helpers when component file exceeds ~80 lines

**Parameters:**
- TypeScript/React: Use object destructuring for props (e.g., `{ session, onSendMessage, submitting, error }`)
- Python: Required positional arguments, optional keyword arguments with defaults
- Dependency injection: FastAPI routes use `Depends()` for injectables (pool, settings, llm, checkpointer)

**Return Values:**
- TypeScript API functions: Return typed Promises (e.g., `Promise<Session>`) or throw `ApiError`
- Python functions: Return explicit types; use `| None` for optional returns
- React components: Return JSX, never null (use conditional rendering instead)

## Module Design

**Exports:**
- TypeScript: Named exports for utilities/types, default export for React components
- Python: Define `__all__` in modules with multiple exports; use `from module import name` style
- API modules export schemas alongside response builders (e.g., `SessionResponse` schema paired with endpoint)

**Barrel Files:**
- Frontend: No barrel files (`__init__.py`/`index.ts`) used; imports are explicit from source
- Backend: Package `__init__.py` files remain minimal; import from submodules directly
- Rationale: Explicit paths aid code navigation and reduce circular dependency risk

**Organization:**
- Logical grouping by domain (e.g., `graph/`, `llm/`, `tools/` in backend; `components/`, `pages/`, `lib/` in frontend)
- Separation of concerns: API schemas, handlers, and repository logic in distinct files
- No cross-module circular dependencies; use dependency injection (FastAPI Depends, LLM provider interface) to break cycles

## Patterns & Best Practices

**Exhaustiveness Checking:**
- Use `Record<UnionType, Value>` in TypeScript instead of switch/if-chains for type unions
- Example: `StatusBadge.tsx` maps `SessionStatus` as `Record<SessionStatus, string>` so adding a status variant causes compile error
- Python: Use `Literal` unions in type hints; mypy catches uncovered cases if `--warn-unreachable-code` enabled

**Dependency Injection:**
- FastAPI: Use `Depends(get_db_pool)`, `Depends(get_settings)`, `Depends(get_llm_provider)` in route signatures
- Fixtures: `@pytest.fixture` factories (e.g., `make_client`) enable test-time overrides via `app.dependency_overrides`
- No module-level singletons except via `@lru_cache` with override pattern

**Testing Doubles:**
- Prefer mocking globals (e.g., `fetch` in tests) over complex fixtures
- Use factory fixtures for parametric test setup (e.g., `make_client(**settings_overrides)`)
- Scripted/fake implementations for complex deps (e.g., `_ScriptedLLM` in integration tests)

---

*Convention analysis: 2026-08-25*
