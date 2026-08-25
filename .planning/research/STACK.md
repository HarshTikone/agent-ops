# Stack Research

**Domain:** Hardening an existing FastAPI + LangGraph + React AI-agent-orchestration copilot for a free-tier solo portfolio deploy (Days 5-7 / fix-prompt Phases 2-7)
**Researched:** 2026-08-25
**Confidence:** MEDIUM (web-search-corroborated across independent sources; no Context7/official-docs MCP available this session — see Sources)

This is **not** a greenfield stack pick. FastAPI 0.141.1 / Python 3.11, LangGraph 1.2.11, React 19.2 + TS 6.0 + Vite 8, Supabase Postgres via psycopg 3.3.4 / psycopg_pool 3.3.1 are locked in (Day 1-2 ADRs) and out of scope. Every recommendation below is scoped to "what's the standard way to bolt hardening onto *this exact* stack on a *free-tier single instance*," per `reviews/day-4-fix-prompt.md` Phases 2-7.

## Recommended Stack

### Core Technologies (additions for this milestone)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `slowapi` | 0.1.10 (already pinned in `requirements.txt`, currently unimported) | Per-IP rate limiting on mutating endpoints | The de facto FastAPI rate-limit library; wraps `limits` (Flask-Limiter's engine) for ASGI. In-memory `MemoryRateLimitStore` (the default) is the *correct* backend here, not a compromise — Redis-backed storage exists specifically to keep counters consistent across multiple processes/instances, which a single Render free-tier instance never has. Already a declared dependency; H1 just needs it wired up. |
| `fastapi.security.api_key.APIKeyHeader` | ships with FastAPI 0.141.1 | Shared-secret auth on mutating endpoints (`POST /sessions/*`, `POST /approvals/*`) | Zero new dependency. `PROJECT.md`'s Out-of-Scope section already rules out Supabase Auth for this milestone — a shared-secret API key is the explicit, correct-sized choice for a single-operator portfolio demo where the only two parties are "the operator" and "everyone else." OAuth2/JWT would add a token-issuance surface with nothing to authenticate *against* (no user table, no multi-tenant need). |
| `mypy` | ^2.3.1 | Static type checking, backend CI gate | Current stable release (verified via PyPI registry, 2026-08-25). Standard companion to `pyproject.toml`-based Python 3.11 projects; integrates with `ruff`/`black` already in the toolchain without overlap (ruff does not type-check). |
| TypeScript `strict` + `noUncheckedIndexedAccess` | already on `typescript ~6.0.2` (no version bump needed) | Compile-time null/undefined safety, frontend CI gate | Both are native `tsconfig.json` compiler flags — no library. The fix-prompt already verified this produces exactly one error in this specific codebase (`src/lib/api.test.ts:75`), so this is a flip-the-flag change, not a multi-week migration — see "TypeScript strict-mode migration" below for why that's plausible for a codebase this size. |
| Native `<dialog>` element | Baseline (all evergreen browsers since 2022) | Accessible `ApprovalModal` (focus trap, Escape, background inert) | Zero new dependency. `showModal()` gives built-in focus trapping, Escape-to-close, a `::backdrop` pseudo-element, top-layer stacking (no z-index fights), and correct `role="dialog" aria-modal` semantics for free — precisely the four things M11 asks for (focus trap, Escape, `inert` background, initial focus). See "Accessible modal pattern" below for the React-specific gotcha. |

### Supporting Libraries / Patterns (no new dependency)

| Pattern | Purpose | When to Use |
|---------|---------|-------------|
| `secrets.compare_digest()` | Timing-safe comparison of the incoming API key against the configured secret | Always, inside the `get_api_key` dependency — a plain `==` on a shared secret leaks the secret's prefix-match length over response-time side channels. Free, stdlib, no reason not to. |
| Module-level `httpx.Client` singleton + FastAPI `lifespan` shutdown hook | Fixes M2 (`WebSearchTool` leaks an `httpx.Client`, rebuilt every `.invoke()`) | Construct once (module import or app startup), close it in the same `lifespan` context manager Phase 2/M1 already needs for the `psycopg_pool.ConnectionPool`. One `lifespan` function, two resources closed on shutdown — don't build two separate startup hooks. |
| `[[tool.mypy.overrides]]` per-module strictness | Retrofitting mypy onto an existing codebase without a rewrite | Only if the initial `mypy app` run under the strict-ish config in H6 (`disallow_untyped_defs`, `warn_unused_ignores`, `no_implicit_optional`) produces more than a handful of errors. Given this codebase's existing discipline (Protocol-based tool interface, typed `Settings`, no `Any` soup visible in the reviewed files), it's plausible mypy passes near-clean on the first pass — check before reaching for overrides. |
| `python:3.11-slim` multi-stage Dockerfile (builder + runtime) | Backend container for Render | Already the shape of `backend/Dockerfile`'s `FROM python:3.11-slim AS base` label — it just isn't actually multi-stage yet (M9's finding: the label promises a structure that doesn't exist). Fix is mechanical, not a new pattern. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `mypy` CI step | `mypy app` in the backend GitHub Actions job, alongside existing `ruff check .` / `black --check .` | Config lives in `pyproject.toml` next to the existing `[tool.ruff]`/`[tool.black]` tables. |
| `tsc -b --noEmit` (already the `build` script's first stage) | TypeScript strict-mode CI gate | No new script needed — `npm run build` already runs `tsc -b` before `vite build`; turning on `strict` in `tsconfig.app.json`/`tsconfig.node.json` makes the existing build step the gate. |

## Installation

```bash
# Backend — slowapi is already in requirements.txt, just import and wire it up.
# mypy is new:
# requirements-dev.txt
mypy==2.3.1

pip install -r backend/requirements-dev.txt
```

```bash
# Frontend — no new packages. strict mode is a tsconfig.json flag flip:
# tsconfig.app.json and tsconfig.node.json:
#   "strict": true,
#   "noUncheckedIndexedAccess": true
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|--------------------------|
| `slowapi` + in-memory store | `fastapi-limiter` / `FastAPI-Cap` (Redis-backed) | Only once you run more than one instance/process (horizontal scaling is an explicit `PROJECT.md` out-of-scope item) or need algorithms beyond fixed/sliding window (token bucket, GCRA). Redis is also a new paid-infra-risk surface — every free Redis tier has stricter limits than Render/Supabase/Vercel free tiers, and it's a service this project doesn't otherwise need. |
| Shared-secret `APIKeyHeader` | Supabase Auth (JWT) | If the project ever needs more than one distinguishable caller (multiple demo users, per-user session ownership) — `PROJECT.md` already recorded this as considered-and-deferred for Day 4, and nothing in Phase 5's scope changes that calculus. JWT also buys nothing here: there's no user table to issue tokens against, so it would be JWT-shaped machinery wrapping the same one shared secret. |
| Native `<dialog>` + hand-rolled `inert` toggle | `focus-trap-react` | If you need to trap focus inside a plain `<div>`-based overlay (e.g., a non-modal popover, or a target browser too old for `<dialog>` — not a real constraint for a 2026 portfolio demo). It solves *only* focus containment; you'd still hand-roll Escape handling and background `inert` yourself, so it doesn't save the work M11 needs done. |
| Native `<dialog>` | Radix UI `Dialog` primitive | If the project needed more than one dialog-shaped component (multiple modal types, nested dialogs, toast-like transient overlays) where sharing one accessible primitive pays for itself. For exactly one modal (`ApprovalModal`) gating one action, Radix is a real dependency (plus its peer deps) bought for functionality the native element already gives for free. |
| Plain `uvicorn app.main:app --workers 1` on Render free tier | Gunicorn + `UvicornWorker` (the generic "don't run uvicorn raw in production" advice) | Once the Render service is upgraded off the 0.1-vCPU free tier. The Gunicorn+multi-worker pattern assumes at least one full CPU core to justify `2 × cores + 1` workers; Render's free tier gives 0.1 vCPU and 512MB RAM, where a second worker process competes for the same fractional CPU slice and adds RAM pressure without adding throughput. Uvicorn's own async event loop already handles concurrency within one process — see "What NOT to Use" below. |
| Per-module `mypy` overrides | A single global `mypy --strict` flip | If the initial clean run confirms the codebase is already near-fully-typed (plausible here — small, LLM-Protocol-first, ADR-013-disciplined codebase). Try the strict config first; only reach for overrides if the error count says otherwise. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|--------------|
| Gunicorn + multiple `UvicornWorker` processes on the Render free instance | Render's free web service is 0.1 vCPU / 512MB RAM. The standard "`(2 × cores) + 1` workers" sizing rule assumes ≥1 full core; on a tenth of one core, a second process only adds RAM overhead (each worker loads the full app) and CPU contention, not throughput. This is the single most-cited free-tier-specific footgun found in research — most Docker/FastAPI guides default to Gunicorn+multi-worker without a free-tier caveat. | Plain `uvicorn app.main:app --host 0.0.0.0 --port $PORT` with the default single worker (this is already what `backend/Dockerfile`'s `CMD` does — leave it as-is, don't "improve" it toward Gunicorn during this hardening pass). If Render is ever upgraded past free tier, revisit. |
| Redis-backed rate limiting (`fastapi-limiter`, Redis-backed `slowapi` storage) | Adds a new paid-infra-risk service for a single-instance app that has no multi-process counter-consistency problem to solve. `PROJECT.md`'s constraint is explicit: "Any paid infrastructure or tier, for any service ... must be flagged and stopped on, never silently used." | `slowapi`'s default in-memory store. |
| JWT / OAuth2 / Supabase Auth for the approval gate | Solves a multi-user identity problem this single-operator demo doesn't have; adds token issuance, refresh, and verification surface for zero additional security value over a compared-in-constant-time shared secret, given there is exactly one legitimate caller. | `APIKeyHeader` + `secrets.compare_digest`, per `PROJECT.md`'s own recorded decision. |
| `focus-trap-react` or Radix `Dialog` for `ApprovalModal` | Both are real dependencies (Radix pulls in several `@radix-ui/*` peer packages) bought to replicate behavior the native `<dialog>` element already provides, for exactly one modal in the app. Adds bundle weight and a new API surface to test against, for a problem `showModal()` already solves. | Native `<dialog ref={...}>` + `showModal()`/`close()`, called imperatively from a `useEffect` keyed on the "is open" prop (conditional JSX rendering of `<dialog open>` does **not** trigger the browser's native modal behavior — this is the one real gotcha, not a reason to reach for a library). |
| A single big-bang `mypy --strict` (all flags, no overrides, no staging) as the first CI-gating commit | Even in disciplined codebases, `--strict`'s full flag set (`disallow_untyped_calls`, `disallow_any_generics`, `disallow_subclassing_any`, etc.) commonly surfaces friction from untyped third-party stubs (`langgraph`, `langchain-*`, `psycopg`) that has nothing to do with this codebase's own type discipline. | The named subset H6 already specifies (`disallow_untyped_defs`, `warn_unused_ignores`, `no_implicit_optional`) as the CI gate, with `[[tool.mypy.overrides]]` reserved for any third-party import that lacks stubs (`ignore_missing_imports = true`, scoped to that module only). |
| Adding a new frontend a11y-testing dependency (e.g. `jest-axe`, `axe-core` wired into Vitest) for this milestone | Out of scope for the specific M11 ask (focus trap, Escape, `inert`) — RTL-based behavioral tests (does focus move into the dialog, does Tab stay inside it, does Escape fire the right handler) already cover what M11 explicitly asks for, without a new dependency. | Vitest + React Testing Library (already installed: `@testing-library/react`, `@testing-library/user-event`), asserting `document.activeElement` and simulated key events directly. |

## Stack Patterns by Variant

**Auth + rate limiting on a single free-tier instance (this project's exact situation):**
- Use `APIKeyHeader` (shared secret) + `slowapi` (in-memory store), both zero-new-paid-infra.
- Because a single operator, a single instance, and a hard no-paid-infra constraint together rule out every alternative (JWT needs a user table to be worth it; Redis-backed limiting needs multiple processes to be worth it) — the "boring" choice is also the objectively correct-sized one here, not a compromise.
- Also: review `allow_credentials=True` in the existing CORS middleware (`main.py`) against whichever header-based scheme ships — a wildcard-methods/headers CORS config with credentials on is generally fine for a header-based API key (it isn't a cookie, so CSRF isn't the concern it would be for cookie auth), but confirm `cors_origin_list` stays a real allowlist, not `*`, once credentials are involved.

**mypy retrofit on an existing, already-decently-typed codebase:**
- Use the named subset (`disallow_untyped_defs`, `warn_unused_ignores`, `no_implicit_optional`) as the initial CI-gating config, not full `--strict`.
- Because the goal (per H6) is "strict enough to be worth having," not maximal strictness — and the fix-prompt's own findings (`Tool` Protocol violations, unhandled `dict | None`) are exactly the class of bug `disallow_untyped_defs` + honest Protocols catch, without needing `disallow_any_generics`-tier strictness that mostly fights third-party stub gaps.

**TypeScript strict-mode migration on a codebase this size:**
- Use the direct flip (`"strict": true, "noUncheckedIndexedAccess": true` in both `tsconfig.app.json` and `tsconfig.node.json`), not a phased sub-flag rollout.
- Because the fix-prompt has already run this experiment and reports exactly one resulting error. Phased rollouts (per-directory overrides, pre-commit-enforced-for-touched-files-only) exist to manage hundreds-of-errors migrations on large legacy codebases — applying that machinery here would be solving a problem this codebase doesn't have.

**Dockerfile for a FastAPI app deployed to Render free tier specifically:**
- Multi-stage (`AS builder` compiles wheels with `build-essential`; runtime stage is `python:3.11-slim` with no compiler toolchain), non-root `USER`, `HEALTHCHECK` against `/health`, `COPY migrations` and `COPY scripts` so `migrate.py` is runnable from the deployed image, single `uvicorn` process (no Gunicorn), `$PORT`-driven `CMD` with no conflicting hardcoded `EXPOSE`.
- Because every item above maps directly to an M9/L21 finding already on file, and the free-tier CPU/RAM ceiling (0.1 vCPU / 512MB) makes single-process the only sizing that makes sense — see "What NOT to Use."

**Accessible modal in a React 19 + Tailwind stack with no heavy dependencies:**
- Use the native `<dialog>` element, driven imperatively via a `ref` and a `useEffect` that calls `showModal()`/`close()` when the "is pending action" prop changes.
- Because React 19 removed the `forwardRef` requirement for passing refs to function components, so wrapping `<dialog>` in an `ApprovalModal` component that accepts an open/close-controlling prop is now a plain function component, not boilerplate — the exact ergonomic gap that used to push people toward `focus-trap-react`/Radix is smaller in React 19 than it was.
- Escape handling: the native `<dialog>` fires a `cancel` event on Escape by default (which then fires `close`) — decide explicitly (per M11's own instruction) whether to let that close the dialog as a no-op-equivalent-to-Reject, or `preventDefault()` the `cancel` event and route Escape through the same handler as the Reject button. Either is defensible; the native element does not make that decision for you, it just gives you the hook to make it deliberately instead of accidentally.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|------------------|-------|
| `mypy` 2.3.1 | Python 3.11 (target-version already `py311` in `pyproject.toml`'s `[tool.ruff]`) | mypy targets are independent of the Python version running it; set `python_version = "3.11"` explicitly in `[tool.mypy]` so it checks against 3.11 stdlib stubs, not whatever version runs CI. |
| `mypy` 2.3.1 | `langgraph` 1.2.11 / `langchain-google-genai` 4.3.5 / `langchain-openai` 1.6.0 | These ship partial or absent type stubs in places (common for fast-moving LLM-orchestration libraries) — expect to need scoped `ignore_missing_imports = true` overrides for specific submodules, not a project-wide blanket ignore. Verify per-package during the actual H6 pass rather than assuming; this is exactly the kind of claim ADR-010/013/017's "verify, don't assume" standard calls out. |
| `slowapi` 0.1.10 | FastAPI 0.141.1 | `slowapi` wraps ASGI middleware generically (via the `limits` library underneath) and has no FastAPI version pin issues; it predates and postdates many FastAPI releases without breaking changes to its own API. |
| Native `<dialog>` `showModal()`/`::backdrop` | All evergreen browsers (Chrome/Edge/Firefox/Safari) | Baseline since 2022 — no polyfill needed for a 2026 portfolio demo audience. The one real interaction to verify by hand: focus return to the trigger element on close, and that Tailwind's `::backdrop` styling target actually applies (Tailwind doesn't include a `backdrop:` variant by default in older major versions — confirm against the installed `tailwindcss` 4.3.3, which does support arbitrary variants like `[&::backdrop]:bg-black/50` if the built-in isn't present). |
| `psycopg_pool` 3.3.1 | `ConnectionPool(open=True)` | Confirmed via official psycopg docs (psycopg.org): implicit-open-in-the-constructor is deprecated for sync pools (warns now, will default to `open=False` later) — call `pool.open()` explicitly, or use `with ConnectionPool(...) as pool:`. The `check=` constructor parameter (added in psycopg_pool 3.2, present in the installed 3.3.1) is the mechanism for M1's "a Supabase idle-drop doesn't hand out a dead connection" — pass `check=ConnectionPool.check_connection` for a ready-made liveness check. This is tangential to this milestone's core 5 questions but directly informs Phase 2/M1 and Phase 5/H7's readiness-dial work, which shares the same pool. |

## Sources

- PyPI registry (`pypi.org/pypi/slowapi/json`, `pypi.org/pypi/mypy/json`) — HIGH confidence, authoritative version numbers (slowapi 0.1.10 released 2026-06-13, mypy 2.3.1 current)
- psycopg official docs (`psycopg.org/psycopg3/docs/api/pool.html`, `.../advanced/pool.html`, `.../news_pool.html`) — HIGH confidence, official project documentation, cross-checked against the `check=` parameter's 3.2 changelog entry and the `open=True` deprecation notice
- WebSearch, multiple independent sources per query (Render's own `render.com/articles/*` blog + third-party benchmarking sites for free-tier CPU/RAM/cold-start figures; `mypy.readthedocs.io` + Wolt engineering blog for incremental mypy adoption; FastAPI's own `fastapi.tiangolo.com/reference/security/` + multiple implementation write-ups for `APIKeyHeader`; MDN/CSS-Tricks/DEV Community consensus for native `<dialog>` vs `focus-trap-react` vs Radix) — MEDIUM confidence (cross-corroborated across 3+ independent sources per topic, no single-source claims carried forward as fact)
- No Context7 or other docs-MCP tool was available in this session; all non-registry findings are WebSearch-sourced. Recommend a follow-up spot-check of the exact `slowapi` `Limiter`/`app.state.limiter` wiring and the native-`<dialog>` React ref pattern against source/MDN directly during implementation (Phase 5 and Phase 6 respectively), since WebSearch digests can compress or slightly misstate exact API shapes.

---
*Stack research for: Agent Ops hardening milestone (Days 5-7 / fix-prompt Phases 2-7)*
*Researched: 2026-08-25*
