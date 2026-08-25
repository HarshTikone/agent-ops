# Architecture Research

**Domain:** Production hardening of a synchronous FastAPI + LangGraph HITL agent backend (persistence durability, auth/rate-limiting middleware, real readiness checks, free-tier container deploy)
**Researched:** 2026-08-25
**Confidence:** MEDIUM (general patterns are well-established and cross-corroborated across independent sources; specifics were verified against this repo's actual code, not guessed)

This is **not** ecosystem-discovery research — Agent Ops's architecture is fixed (see `ARCHITECTURE.md` §1-9 at repo root, `.planning/PROJECT.md`). This file answers: what is the standard *shape* of the four remaining pieces of work (transactional persistence, auth+rate-limit middleware, real `/health/ready`, Render+Vercel+Supabase deploy), and where do they attach to the existing system without restructuring it.

## Standard Architecture

### System Overview — where the new pieces attach

```
┌──────────────────────────────────────────────────────────────────────┐
│  Vercel (static)              Render (FastAPI, free web service)     │
│  ┌─────────────┐              ┌──────────────────────────────────┐  │
│  │ React SPA   │──HTTPS──────▶│ 0. CORSMiddleware (outermost)     │  │
│  │ (build-time │  X-API-Key   │ 1. SlowAPIMiddleware              │  │
│  │  VITE_API_  │  header      │ 2. [existing routers, unchanged]  │  │
│  │  URL baked  │              │    sessions / approvals / health  │  │
│  │  in)        │              │    -- auth via router-level       │  │
│  └─────────────┘              │    Depends(verify_api_key), not   │  │
│                                │    per-handler edits              │  │
│                                └───────────┬────────────────────────┘  │
│                                            │                          │
│                                  lifespan-managed                    │
│                                  ConnectionPool (app.state)           │
│                                            │                          │
│                                ┌───────────▼────────────────────────┐  │
│                                │ session_runner._apply_result()    │  │
│                                │   -- Phase 2 target: one txn per  │  │
│                                │      graph .invoke() result        │  │
│                                └───────────┬────────────────────────┘  │
└────────────────────────────────────────────┼──────────────────────────┘
                                              │
                                   ┌──────────▼──────────────┐
                                   │ Supabase Postgres        │
                                   │ (free tier, pauses after │
                                   │  7d — /health/ready must │
                                   │  detect HTTP 540)         │
                                   └───────────────────────────┘
```

The existing request flow (`sessions.send_message` → `session_runner.start_session_run` → `graph.invoke()` → `_apply_result()`) does not change shape. What changes: (a) `_apply_result` becomes one transaction instead of 2-4 autocommit statements, (b) two middleware layers wrap the existing routers, (c) `/health/ready` gains a real dependency dial, (d) the whole backend gets a multi-stage Dockerfile.

### Component Responsibilities

| Component | Responsibility | Where it sits |
|-----------|----------------|----------------|
| `app/db.py` `lifespan` (new) | Opens the pool once at process start with a `check` callback, closes it on shutdown | FastAPI `lifespan=` param on `FastAPI(...)`, replacing the current `open=True` eager-construct-at-import pattern |
| `repository.py` transaction helper (new) | One Postgres transaction per logical outcome (interrupt / done / failed) instead of N independent autocommit statements | Called from `session_runner._apply_result`, not from the API layer — the API layer's shape is untouched |
| Auth dependency (new) | Rejects unauthenticated calls to mutating endpoints | `APIRouter(dependencies=[Depends(verify_api_key)])` on `sessions.router` and `approvals.router` — zero changes inside existing handler bodies |
| `SlowAPIMiddleware` + `Limiter` (new) | Per-IP rate limit on mutating endpoints | `app.add_middleware()` in `main.py`, decorators only on the specific mutating handlers that need a tighter limit than the default |
| `/health/ready` (amended) | Reports whether Postgres and the configured LLM provider(s) are actually reachable, not just configured | Existing router, existing route — body changes from string-truthiness checks to a real `SELECT 1` + provider ping, same three-way status contract (ADR-009) |
| Dockerfile (rewritten) | Non-root, multi-stage, ships `migrations/`+`scripts/`, `HEALTHCHECK` against `/health` | `backend/Dockerfile` — build order concern, not a new component |

## Question 1 — The synchronous-request / durable-persistence boundary

### The standard pattern: "commit or crash-safe, never half"

Production HITL agent backends that run the agent graph synchronously inside an HTTP request (rather than a background worker) converge on the same rule: **the boundary between "ran the graph" and "wrote the outcome" must be one atomic unit**, because the request can die at any point between them (process kill, OOM, deploy restart, DB blip) and there is no supervisor to retry a half-applied write. Two concrete mechanisms are standard:

1. **Wrap the whole outcome-application step in one DB transaction.** This project's own Phase 1 fix (C4) already established the first half of this discipline — wrap `start_session_run`/`resume_session_run` in `try`/`except` so a raised exception can't leave `sessions.status='running'` forever. Phase 2's job is the second half: `_apply_result()` itself currently issues 2-4 *independent* autocommit statements (`create_pending_action`, then a separate `update_session_status`; or `add_message` then `update_session_status`). The standard fix is not new — it's the same "outbox"-adjacent idea as transactional writes anywhere: acquire one connection, `BEGIN`, do every write for this outcome, `COMMIT`, and if anything raises, the whole transaction rolls back and the session is left in whatever state it was in *before* this call — which is `running` (already durable from the previous commit), not a new inconsistent state. `try`/`except` around the call site (already fixed) then flips it to `failed`. The two fixes compose: transactional `_apply_result` guarantees no *partial* write; the C4 `try`/`except` guarantees no *unnoticed hang* if `_apply_result` itself raises.
2. **A crash mid-transaction is safe by construction** because Postgres either commits the whole thing or none of it — the graph's own state (LangGraph checkpoint via `PostgresSaver`, already committed by `graph.invoke()` before it returns) is the source of truth for "what step is next"; `_apply_result`'s job is purely to *reflect* that outcome into the app-facing tables (`sessions`, `pending_actions`, `trace_events`). This is why the two persistence layers (checkpoint tables vs. `sessions`/`trace_events`) can be separate transactions from each other (checkpoint commits inside `graph.invoke()`, app tables commit in `_apply_result()`) without creating a two-phase-commit problem: if the process dies between them, the checkpoint is already durably at the new state, and the next request (a retry, or the crash-recovery `try`/`except` marking the session `failed`) reconciles the app tables against it. **The graph checkpoint is upstream of the app tables in the recovery order** — this is the specific reason `_apply_result`'s transaction doesn't need to also cover the graph's own checkpoint write.

### Standard trace-log durability pattern: sequence number, not row count

The count-based diff this project currently has (`len(list_trace_events(...))` used as a slice offset into the in-memory trace) is a known anti-pattern: **using `COUNT` (or `len()` of a full row fetch) as a resume cursor is never durable**, because a deleted row, a duplicate insert, or a divergence between what got persisted and what's still in the in-process list silently corrupts the offset forever, with no way to detect it happened. The standard fix in every durable-log design (this is the same principle as Kafka consumer offsets, outbox pattern sequence numbers, or event-sourcing stream versions) is a **monotonic sequence number per session**, either:
- a Postgres `SERIAL`/`IDENTITY` column with a `UNIQUE (session_id, seq)` constraint, diffed by `MAX(seq) WHERE session_id = ...` instead of `COUNT(*)`, or
- writing trace rows *inside* the same transaction as the outcome write (folds into the Phase 2 transaction directly, making the "diff" problem disappear because there's no cross-request accumulation to reconcile — every `_apply_result` call only ever writes the events new to *this* invocation).

Given this project already needs one transaction per `_apply_result` call (H2), folding H3's fix into the same transaction is the lower-risk path: it eliminates the diff-by-count entirely rather than replacing one cursor scheme with another.

### Build order implication

Persistence hardening (H2 transactional `_apply_result`, H3 sequence-based trace diff, H4 `provider` field, M3 `final_answer` sentinel guard, M1 pool lifespan) has **no dependency on** auth/rate-limiting or readiness — they touch different files (`repository.py`, `session_runner.py`, `db.py`) than auth (`main.py`, new `app/auth.py`) and readiness (`app/api/health.py`). They *can* run in parallel phases. The one true ordering constraint: **M1's pool lifespan (opening the pool with a `check` callback, and attaching it via `app.state` or a dependency) should land before H7's readiness fix**, because H7's real `SELECT 1` dial needs a pool that's guaranteed open and has dead-connection detection — dialing a pool that might hand back a stale connection makes the readiness check itself unreliable, which is exactly the flakiness H7 is supposed to eliminate.

## Question 2 — Adding auth + rate-limiting middleware without restructuring routes

### Auth: router-level `Depends`, not per-handler edits

The standard FastAPI retrofit pattern for adding auth to an *existing* app is to **attach the dependency at the `APIRouter` (or `FastAPI`) level, not inside each handler**:

```python
# app/auth.py — new file, zero changes to existing handler bodies
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def require_api_key(key: str = Security(_api_key_header)) -> None:
    if key != settings.api_key:  # constant-time compare in the real impl
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")
```

```python
# sessions.py / approvals.py — only the router construction line changes
router = APIRouter(prefix="/sessions", dependencies=[Depends(require_api_key)])
```

This is the mechanism that satisfies "without restructuring route handlers": the dependency is evaluated before the handler body runs, on every route under that router, and the handler functions themselves need no new parameter, no new import, no signature change. `health.router` (liveness/readiness) stays **unauthenticated** — deliberately, since uptime monitors and the Render/orchestrator health check must be able to reach it without a key, and readiness needs to be checkable by anything, including a human debugging a "why is this not_ready" without prior credentials.

`GET /sessions` and the mutating endpoints (`POST /sessions/{id}/messages`, `POST /approvals/{id}/approve|reject`) are exactly what H1 flags as unauthenticated today — router-level `dependencies=[...]` on `sessions.router` and `approvals.router` covers all of them in two lines, matching this project's existing router-per-resource file layout (`app/api/sessions.py`, `app/api/approvals.py`).

**CORS interaction (from PROJECT.md's own flag):** with `allow_credentials=True` currently set, review whether it's still needed once auth moves to a header (`X-API-Key`) rather than a cookie — header-based auth does not require `allow_credentials=True`, and combined with `allow_origins=["*"]` (if that's ever loosened) browsers reject the combination outright. The standard, safe combination for a header-auth SPA-to-API setup is an **explicit origin allowlist** (already what `cors_origin_list` does) with `allow_credentials=False`, unless a future Supabase-Auth-cookie path is added later.

### Rate limiting: `slowapi`, middleware + decorator, handler registered first

`slowapi` (already declared, unused) is the standard lightweight choice for a single-instance FastAPI deployment — it wraps `limits`, defaults to an in-memory backend (no Redis needed, which matters for the free-tier/no-paid-infra constraint), and is the most common FastAPI-ecosystem answer for "add rate limiting without a new service." Standard wiring:

```python
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # before the middleware
app.add_middleware(SlowAPIMiddleware)
```

then either a global `default_limits=[...]` on the `Limiter`, or `@limiter.limit("N/minute")` decorators on the specific mutating handlers (`send_message`, `approve`, `reject`) — this project should prefer **per-route decorators on the mutating endpoints specifically**, since PROJECT.md's stated purpose for rate limiting is capping *irreversible-action* and *LLM-cost-incurring* endpoints, not blanket-limiting `GET /health`.

Two retrofit-specific gotchas confirmed from source patterns: (1) the exception handler **must be registered before** `SlowAPIMiddleware` is added — reversing the order is a common bug; (2) every rate-limited endpoint's signature must already accept `request: Request` for `slowapi` to key off it — this project's existing handlers already take `request`/`Request`-typed params in most cases (verify per-handler), so this is a near-zero-diff addition, not a rewrite.

**Ordering between auth and rate limiting:** rate-limit by IP (`get_remote_address`), which needs no auth context, so **the two are independent and can land in either order** — but doing auth first is slightly cheaper to reason about: an unauthenticated 401 short-circuits before hitting a rate-limited handler at all if auth is a `Depends` (dependency resolution happens inside route handling, after `SlowAPIMiddleware` has already counted the request) — meaning rate limiting counts *every* request including rejected/unauthenticated ones regardless of order, which is actually the correct behavior for its purpose (stopping a hammering client, authenticated or not).

## Question 3 — Where `/health/ready` sits and how it stays fast/reliable

### Liveness vs. readiness: keep them structurally separate (already the case here)

This project already has the correct split — `/health` (liveness, always 200, no dependency checks) and `/health/ready` (readiness, checks dependencies) — matching the standard container-platform convention (originally Kubernetes probe semantics, but the same split applies to any platform with a health-check-driven routing/restart decision, including Render's own health check config):

- **Liveness must stay trivial and dependency-free.** Its only signal is "is the process able to respond at all" — adding a DB dial here means a transient Postgres blip causes a *restart* (a heavier, slower recovery than needed) instead of just a *not-ready* signal. This project's `/health` already does this correctly (returns `{"status": "ok"}` unconditionally) and Phase 5 should not change that.
- **Readiness checks real dependencies but must stay light and bounded.** The standard shape is a single `SELECT 1` (or equivalent minimal round-trip) with a short, explicit timeout — not the default request timeout, which is often too generous for a check that needs to fail fast. Checking multiple dependencies serially with no per-check timeout is the standard way a readiness endpoint becomes the slow/flaky thing it's supposed to detect; the fix is to bound each dial individually (e.g. `pool.connection(timeout=2)` or a `psycopg` statement_timeout) so one wedged dependency can't make the *health check itself* hang.

### Applying this to H7 specifically

The concrete change this project needs: replace `checks["supabase_configured"]`/`checks["database_configured"]` (string-truthiness only) with an actual `SELECT 1` through `get_db_pool()`, wrapped in a short timeout, and keep it as a **separate field** from the existing config-truthiness checks (PROJECT.md/fix-prompt already call this out: "so the frontend can still tell 'misconfigured' from 'unreachable'"). This preserves the existing ADR-009 three-way contract (`ready` / `degraded` / `not_ready`) — `degraded` still means "Gemini-only, no OpenRouter failover", `not_ready` now additionally covers "Postgres configured but unreachable" (e.g. a paused Supabase project answering HTTP 540), which is the literal gap H7 exists to close.

For the LLM-provider side of "reachable, not just configured": a *full* generation call against Gemini/OpenRouter on every readiness poll is the wrong shape (costs real quota on every health check, and is slow) — the standard compromise is to keep the LLM check as **configuration validity only** (already correct, per ADR-009's own reasoning: a missing/malformed key is a real, cheap-to-detect failure mode; an actual outage is instead caught by the existing failover + trace-logged mechanism at request time, not by readiness). Only the *database* dependency gets a real network dial in the standard pattern, because a DB outage is silent and total (every request fails) whereas an LLM provider outage already has a runtime mitigation (`FailoverProvider`) that readiness doesn't need to duplicate.

### Build order implication

H7 (real readiness) should land **after** M1 (pool lifespan + `check` callback), for the reason in Question 1: dialing a pool without dead-connection detection makes the readiness check unreliable in exactly the scenario it's meant to catch. H7 should land **before** the Docker/deploy phase (Day 6), since Render's own health-check-driven behavior (see Question 4) depends on `/health` — not `/health/ready` — being fast and truthful, and verifying that in a container is far cheaper before the deploy step than debugging it after.

## Question 4 — Render (free) + Vercel (free) + Supabase (free) deploy topology

### Standard topology

```
GitHub repo (main branch)
      │
      ├── Vercel: auto-deploy on push, builds frontend/ as a static
      │   site, injects VITE_API_URL at BUILD time (baked into the
      │   bundle, not runtime-configurable after build)
      │
      └── Render: auto-deploy on push, builds backend/Dockerfile,
          injects DATABASE_URL / GEMINI_API_KEY / OPENROUTER_API_KEY /
          API_KEY / CORS_ORIGINS as runtime env vars, binds to $PORT
                    │
                    ▼
          Supabase Postgres (free project, separate lifecycle —
          not deployed by this pipeline; pauses independently after
          7 days of DB inactivity)
```

### What commonly gets missed (cross-checked across multiple independent write-ups, not a single source)

1. **`VITE_API_URL` is a build-time value, not a runtime one.** Vite inlines `import.meta.env.VITE_*` into the built JS at `npm run build` time. Setting the env var in Vercel's dashboard only takes effect on the *next* build/redeploy — a common failure mode is updating the var after the backend's Render URL is known, then not triggering a rebuild, leaving the deployed bundle pointed at `localhost` or `undefined`. This project's L2 fix ("throw at module load when `import.meta.env.PROD` and the variable is unset") is the standard mitigation — fail loud in the built bundle rather than silently calling `localhost` from production.
2. **CORS origin string must include the scheme** (`https://agent-ops.vercel.app`, not `agent-ops.vercel.app`) — a bare-domain `CORS_ORIGINS` value is a commonly reported silent failure, since `CORSMiddleware`'s origin match is exact-string, not host-only.
3. **`allow_credentials=True` + wildcard origins is invalid** and browsers reject it outright; since this project moves to header-based (`X-API-Key`) auth rather than cookies, `allow_credentials` likely doesn't need to be `True` at all post-H1 — worth an explicit decision, not a leftover default.
4. **Preview/branch deployments need their own origin handling.** Not applicable here if Vercel previews aren't part of this project's workflow, but worth noting: a static `CORS_ORIGINS` env var only covers the production Vercel URL — if PR-preview URLs from Vercel ever need to hit the Render backend, the static allowlist approach doesn't cover them (out of scope for a solo portfolio build, flagged for completeness).
5. **Render's free-tier spin-down (15 min idle → cold start ~30-60s) is orthogonal to Supabase's pause (7 days idle → HTTP 540), and both need separate handling.** Render's own health check (configured in the Render dashboard against `/health`, not `/health/ready`) is what Render uses to decide the service is up post-deploy and post-wake — pointing Render's health check at `/health/ready` instead of `/health` is a real mistake to avoid, because a `not_ready` response (e.g. Supabase legitimately paused) would then make Render treat the *whole service* as failed-to-deploy/unhealthy and potentially loop-restart it, when the correct behavior is "the process is fine, one dependency isn't" — exactly the liveness/readiness distinction from Question 3. **This project's README already documents "how to wake" a paused Supabase project (§5)** — the deploy-topology-specific addition is making sure Render's dashboard health-check path is `/health`, and any uptime-style keep-alive pinger (if used) targets `/health` too, not `/health/ready` (which would trigger a real DB dial on every ping — wasteful and, per Question 3, the wrong endpoint to hammer for a keep-alive signal anyway).
6. **The two free-tier sleep behaviors compound in a specific bad way for a portfolio demo:** if both Render and Supabase are simultaneously cold (plausible after a weekend of no traffic), the first real visitor's first request pays *both* costs — Render's ~30-60s container cold start *and*, once the container is up, a `/health/ready` or first real query hitting an actually-paused Supabase project. The standard mitigation given the free-tier-only constraint is not to eliminate this (no paid tier allowed) but to make it **visibly diagnosable**: `/health/ready`'s `not_ready` + per-dependency-reason payload (already the design per H7) lets the frontend's `BackendStatus` component show "database waking up" rather than a bare failed fetch — turning an otherwise-confusing multi-minute blank screen into an explained, expected state, which is the realistic free-tier answer rather than pretending the sleep behavior can be fully hidden.

### Dockerfile / build-order specifics (M9)

The current single-stage Dockerfile (`FROM python:3.11-slim AS base`, no second stage despite the `AS base` label, running as root, `build-essential` shipped into the runtime image, `migrations/`/`scripts/` not copied in) needs the standard **builder + runtime split**: a `builder` stage installs `build-essential` and compiles wheels, a `runtime` stage (`COPY --from=builder`) contains only the installed packages plus `app/`, `migrations/`, `scripts/` — `migrate.py` currently cannot run inside the deployed image at all, which is a real Day 6 blocker since Render's deploy step needs to run migrations against the (already-provisioned, separately-managed) Supabase database as part of getting a fresh environment to a working schema. Add `USER app` (non-root) after the final `COPY`, and a `HEALTHCHECK CMD curl -f http://localhost:${PORT}/health` — pointed at liveness, not readiness, for the same reason as Render's own dashboard health check (item 5 above).

### Build order implication (Docker/deploy phase)

Docker (M9) depends on nothing from auth/rate-limiting/readiness *functionally* (the image builds regardless), but **should land after H7 and M1**, because the `HEALTHCHECK` directive and Render's dashboard health-check config are only meaningful once `/health` (liveness) is confirmed cheap and `/health/ready` reflects real state — building and shipping the container before those land just means re-deploying once they do. The natural sequence for Days 5-6, given all four questions above: **(1) persistence transaction/pool-lifespan work → (2) auth + rate-limiting middleware → (3) real readiness → (4) Docker + Render/Vercel deploy**, with (1) and (2) safely parallelizable against each other (they touch disjoint files) but both gating (3), and (3) gating (4).

## Anti-Patterns to Avoid

### Anti-Pattern 1: Readiness check that dials the LLM provider with a real generation call

**What people do:** make `/health/ready` "truly" verify the LLM provider by sending it a real prompt.
**Why it's wrong:** burns real quota (a scarce, non-renewable free-tier resource here) on every poll, and is slow/flaky exactly because network calls to a third party are the least reliable thing to put in a tight health-check loop — this directly recreates the "slow/flaky endpoint" failure mode the question warns against.
**Do this instead:** keep the LLM check as configuration-validity only (already this project's design intent per ADR-009); rely on `FailoverProvider` + trace logging to surface a real outage at request time, where it's already handled.

### Anti-Pattern 2: Pointing a platform's health-check config at the readiness endpoint

**What people do:** wire Render's (or any PaaS's) dashboard health check, or an external uptime pinger, at `/health/ready` instead of `/health`.
**Why it's wrong:** couples the platform's up/down decision (and any auto-restart behavior) to a dependency the process itself has no control over (e.g. Supabase paused) — turns a "one dependency is down" situation into "the whole service is reported unhealthy," which can trigger unwanted restart loops and defeats the entire purpose of separating liveness from readiness.
**Do this instead:** platform health checks and uptime pingers target `/health`; only the frontend's own `BackendStatus` component (and a human debugging) should read `/health/ready`.

### Anti-Pattern 3: Rewriting route handlers to add auth/rate-limit checks inline

**What people do:** add `if request.headers.get("X-API-Key") != settings.api_key: raise HTTPException(...)` as the first line of every mutating handler.
**Why it's wrong:** duplicates the check N times, is easy to forget on a new endpoint, and is exactly the "restructuring route handlers" this question explicitly asks to avoid.
**Do this instead:** router-level `dependencies=[Depends(require_api_key)]` — one line per router, zero handler-body changes, and a new endpoint added under that router is protected automatically rather than by remembering to add a check.

## Sources

- [FastAPI + psycopg lifespan pattern discussion (psycopg/psycopg#985)](https://github.com/psycopg/psycopg/discussions/985) — MEDIUM confidence (community discussion, cross-checked against official psycopg docs pattern)
- [psycopg3 connection pool docs (`check` callback, context-manager close semantics)](https://www.psycopg.org/psycopg3/docs/advanced/pool.html) — MEDIUM confidence
- [slowapi setup pattern and per-route decorator usage (Medium/CodeSignal/bytescrum write-ups)](https://slowapi.readthedocs.io/) — LOW confidence on the CORS-ordering specifics (no single authoritative source confirmed the exact ordering vs. `CORSMiddleware`; flagged as a decision to verify empirically during implementation, not import as fact)
- [FastAPI official APIKeyHeader security docs](https://fastapi.tiangolo.com/reference/security/) and router-level `dependencies=[...]` retrofit pattern (multiple corroborating write-ups) — MEDIUM confidence
- [Render free-tier spin-down behavior, official + community corroboration](https://github.com/orgs/community/discussions/197645) — MEDIUM confidence, consistent across ~6 independent sources (15-minute idle threshold, 30-60s cold start)
- [Supabase official docs — free project pausing](https://supabase.com/docs/guides/platform/free-project-pausing) — MEDIUM confidence (7-day threshold, HTTP 540 on paused project, corroborated across official docs + multiple community write-ups)
- [Kubernetes-pattern liveness/readiness split applied to FastAPI (oneuptime.com, patrykgolabek.dev, kubernetes.io probes docs)](https://kubernetes.io/docs/concepts/workloads/pods/probes/) — MEDIUM confidence, this is a very well-established, widely-corroborated pattern
- Community write-ups on Vercel/Render CORS + env-var wiring mistakes (multiple Medium/DEV Community sources, cross-checked for consistency) — MEDIUM confidence
- Direct source verification: this project's own `backend/app/main.py`, `app/config.py`, `app/db.py`, `app/session_runner.py`, `app/api/health.py`, `Dockerfile`, `requirements.txt` (read directly, HIGH confidence — this is what grounds every recommendation above in the actual codebase rather than a generic template)

---
*Architecture research for: production HITL agent backend hardening (persistence, auth, readiness, free-tier deploy)*
*Researched: 2026-08-25*
