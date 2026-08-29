# Sprint 02 — Security and Operational Readiness

> **Status: completed (2026-08-28).** Implemented and verified locally; public
> Render/Vercel deployment remains the next sprint.

## Sprint goal

Protect every state-changing and quota-consuming operation, make dependency
health truthful, and give all database and HTTP resources an explicit lifecycle.

The application should finish this sprint safe to place behind a public URL,
although the actual Render/Vercel deployment remains a separate sprint.

## Duration and capacity

- Duration: 5 focused development days
- Target capacity: 20–25 engineering hours
- Delivery strategy: four independently reviewable work packages
- Feature policy: no new tools, planner behavior, streaming, or account system

## Success criteria

- Unauthenticated clients cannot mutate state, approve actions, or consume LLM
  and tool quota.
- Authentication uses constant-time comparison and never logs or returns the
  operator token.
- Mutation requests are rate-limited and return a stable `429` response.
- Message, rejection, note, search-query, and list-limit inputs are validated
  at the server boundary.
- `/health/ready` proves the database is reachable within a short timeout while
  preserving `ready`/`degraded`/`not_ready` semantics.
- Database pools and shared HTTP clients are created and closed through the
  FastAPI application lifespan.
- No adapter exception escapes the tool-call boundary as an unclassified crash.
- The backend container is non-root, multi-stage, migration-capable, and has a
  liveness health check.
- All default CI checks remain secret-free and green.

## Work package 1 — Authentication, validation, and rate limiting

### Objective

Secure every mutation and bound every user-controlled input before public
deployment.

### Tasks

- Add `AGENT_OPS_API_KEY` to backend settings with production validation.
- Implement one FastAPI dependency that validates an `X-Agent-Ops-Key` header
  using `secrets.compare_digest`.
- Require that dependency on:
  - `POST /sessions`
  - `POST /sessions/{id}/messages`
  - `POST /approvals/{id}/approve`
  - `POST /approvals/{id}/reject`
- Keep liveness, readiness, session reads, and trace reads unauthenticated for
  demo observability unless a documented threat-model review says otherwise.
- Add SlowAPI limits to mutation endpoints, with stricter limits for message
  execution and approval resumption than session-shell creation.
- Return consistent JSON for `401` and `429` without revealing whether a token
  was close to correct.
- Add server-side constraints for:
  - message content: trimmed, non-empty, maximum length
  - rejection reason: optional but length-bounded
  - note key/content and web-search query
  - session-list limit, with a safe range
- Add frontend runtime token entry and send the header only on mutation calls.
- Store the token in memory or `sessionStorage`; never compile it into the Vite
  bundle, commit it, log it, or place it in URLs.
- Add API, rate-limit, validation, and frontend request-header tests.

### Acceptance criteria

- Missing or incorrect credentials receive `401` before provider or tool
  construction begins.
- Valid credentials preserve every existing mutation flow.
- The configured request threshold produces `429`, with tests that reset
  limiter state and do not depend on execution order.
- Empty, whitespace-only, and oversized inputs receive `422` without touching
  the graph or database mutation path.
- A production frontend bundle contains no operator token.

### Estimate

6–7 hours

## Work package 2 — Application lifecycle and truthful readiness

### Objective

Own infrastructure resources explicitly and distinguish configured dependencies
from reachable dependencies.

### Tasks

- Replace import-time resource construction with a FastAPI lifespan context.
- Open the database pool during startup and close it during shutdown.
- Configure the pool with a connection-check callback so dead Supabase
  connections are discarded before use.
- Create one shared `httpx.Client` for web search during startup and close it on
  shutdown.
- Pass application-owned resources through dependencies and the tool registry.
- Update `/health/ready` to perform a timed `SELECT 1` against PostgreSQL.
- Use an explicit short readiness timeout that cannot occupy the request thread
  or pool indefinitely during a Supabase resume.
- Preserve the current semantics:
  - `ready`: required dependencies reachable and fallback configured
  - `degraded`: required dependencies reachable, optional fallback absent
  - `not_ready`: required configuration missing or database unreachable
- Keep `/health` dependency-free and always suitable as the platform liveness
  endpoint.
- Add startup, shutdown, dead-connection, timeout, and readiness-state tests.

### Acceptance criteria

- TestClient lifespan tests prove the pool and HTTP client close exactly once.
- A configured but unreachable database returns `not_ready` within the timeout.
- Missing OpenRouter configuration still produces `degraded`, not `not_ready`.
- `/health` does not dial the database or any provider.
- Repeated web searches reuse one client rather than creating new clients.

### Estimate

5–6 hours

## Work package 3 — Tool and exception boundaries

### Objective

Ensure malformed data, network failures, and adapter bugs become observable
step failures instead of crashing a session.

### Tasks

- Expand notes-store database handling beyond `OperationalError` and classify
  connection/transient errors separately from constraint/input failures.
- Cover additional HTTPX transport failures such as `ReadError`,
  `WriteError`, and `RemoteProtocolError` in web search.
- Add a final `except Exception` backstop in `tool_call_node` that:
  - logs the traceback
  - records an error-level trace event
  - classifies the failure as permanent
  - never includes secrets or full upstream response bodies
- Keep expected `ToolError` handling narrow and unchanged ahead of the backstop.
- Sanitize stored crash traces so provider or database exceptions cannot persist
  credentials, authorization headers, or connection strings.
- Add mutation-oriented tests that make each adapter raise one unexpected
  exception and verify the graph reaches replan/give-up instead of crashing.
- Make `LLMProvider` runtime-checkable and give `FailoverProvider` an explicit
  `name` instead of relying on `getattr` fallbacks.

### Acceptance criteria

- No tool exception crosses `tool_call_node` unclassified.
- Transient transport/database failures remain retryable.
- Programmer errors are logged with traceback but exposed to users and traces
  only through sanitized summaries.
- Failover logging uses explicit provider names.
- New tests pass against deliberate mutations that remove each exception
  boundary.

### Estimate

4–5 hours

## Work package 4 — Container and operational packaging

### Objective

Make the backend artifact safe and complete enough for the deployment sprint.

### Tasks

- Convert the backend Dockerfile to a genuine builder/runtime multi-stage image.
- Keep compilers and build headers out of the runtime stage.
- Create and run as a non-root application user.
- Copy `migrations/` and `scripts/` into the runtime image.
- Add a liveness `HEALTHCHECK` against `/health`, never `/health/ready`.
- Confirm `python -m scripts.migrate` works inside the built image.
- Add a `.dockerignore` review to exclude environments, caches, tests, secrets,
  and local artifacts without excluding required runtime files.
- Remove unused `tenacity` and `structlog`, or use them deliberately and add
  tests demonstrating their purpose.
- Add a container smoke script or CI step that builds the image, runs migrations
  against the CI PostgreSQL service, starts the API, and probes `/health`.

### Acceptance criteria

- Image inspection confirms the runtime user is not root.
- Build tooling is absent from the runtime stage.
- Migration files and runner are present and executable.
- Container liveness succeeds while readiness may independently report
  dependency degradation.
- No `.env`, credentials, local database state, or test cache appears in image
  history or filesystem.

### Estimate

4–5 hours

## Suggested daily sequence

### Day 1

- Add backend authentication dependency and settings.
- Protect all mutations and add API tests.
- Add frontend runtime credential handling.

### Day 2

- Add validation models and rate limiting.
- Complete frontend header and validation UX tests.
- Confirm unauthenticated requests never construct providers.

### Day 3

- Introduce FastAPI lifespan resource ownership.
- Add pool checking, shared HTTP client, and timed database readiness.
- Add lifecycle/readiness tests.

### Day 4

- Harden notes and web-search exception translation.
- Add the tool-call catch-all and sanitization tests.
- Complete runtime-checkable provider typing.

### Day 5

- Harden the backend Docker image and add container smoke validation.
- Run the complete validation matrix.
- Perform a final diff review and update ADR/architecture/requirements.

## Required test matrix

### Backend

- Authentication: missing, incorrect, correct, and blank production key
- Authorization ordering: rejected before LLM/checkpointer construction
- Rate limiting: below threshold, threshold exceeded, isolated test state
- Validation: boundary lengths, whitespace, Unicode, malformed UUIDs
- Readiness: reachable DB, refused connection, timeout, missing fallback
- Lifecycle: startup failure, normal shutdown, client/pool closed exactly once
- Tools: each expected transport/database error plus unexpected exception
- Regression: create → message → approval → execute → done

### Frontend

- Mutation requests include the runtime token
- Read requests do not unnecessarily expose it
- Missing token produces a clear operator prompt
- `401`, `422`, and `429` show actionable, non-secret error messages
- Strict TypeScript, Vitest, ESLint, Prettier, and production build

### Container

- Image builds from a clean checkout
- Runtime UID is non-zero
- Migration runner sees all forward migrations
- `/health` succeeds from inside the container network
- No secret-bearing file is copied into the image

## Explicitly deferred

- Approval-dialog focus trap and broader accessibility polish
- Error boundary, not-found route, and remaining frontend UX items
- Render and Vercel deployment
- Public demo copy, screenshots, and README problem-first rewrite
- Streaming/SSE, session deletion, pagination, semantic memory, and new tools

These form the deployment-and-demo sprint after this security gate is complete.

## Risks and controls

- **A browser-delivered token is visible to its operator.** Treat it as a
  single-operator control, never an end-user identity system. Do not bake it
  into `VITE_*` variables; enter it at runtime and rotate it if shared.
- **In-memory rate limits are instance-local.** This project deliberately
  deploys one Render instance. Revisit distributed storage only if horizontal
  scaling enters scope.
- **Readiness checks can become an outage amplifier.** Use a short timeout and
  one small `SELECT 1`; never call an LLM from readiness.
- **A global catch-all can hide programmer defects.** Log traceback and retain
  an error-level trace while returning only a sanitized classification.
- **Lifespan refactoring touches tests and dependency overrides.** Land it as a
  dedicated work package before changing tool adapters.

## Definition of done

- All acceptance criteria are covered by automated tests.
- Backend and frontend default CI run with no external-provider secrets.
- Ruff, Black, mypy, pytest, ESLint, Prettier, Vitest, strict TypeScript, Vite
  build, and container smoke checks pass.
- No credentials appear in logs, trace rows, response bodies, frontend bundles,
  Docker layers, or committed files.
- The sprint-end code review has no unresolved actionable findings.
- `PROJECT.md`, `REQUIREMENTS.md`, `ARCHITECTURE.md`, and append-only ADRs match
  the implemented behavior.
- The project is ready for the next sprint: accessibility, deployment, and demo
  completion.
