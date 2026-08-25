# Project Research Summary

**Project:** Agent Ops
**Domain:** AI agent orchestration copilot (LangGraph-based, human-in-the-loop) — subsequent milestone (Days 5-7 hardening on top of a working Days 1-4 system)
**Researched:** 2026-08-25
**Confidence:** MEDIUM

## Executive Summary

Agent Ops is a mature, single-operator HITL agent orchestrator with a defensible one-way approval state machine already in place (`pending → approved/rejected → executed`) and a full Day 1-4 code review already closed out. The Days 5-7 hardening pass — persistence durability, type safety, tool-adapter error handling, auth/rate-limiting/readiness, accessible frontend, deploy — exists to make the "production-grade reliability" claim in `PROJECT.md`'s Core Value credible under failure, not just under the happy path.

The recommended approach across every dimension researched is the same: use boring, battle-tested, already-declared-or-zero-dependency patterns rather than reaching for enterprise-scale tooling this project's single-operator, single-instance, free-tier constraints don't call for. Concretely: `slowapi` in-memory rate limiting (already a declared but unused dependency) over Redis-backed limiting; a shared-secret `APIKeyHeader` over OAuth2/JWT; native `<dialog>` + `showModal()` over a focus-trap library; a named mypy strictness subset over full `--strict`; a direct TypeScript `strict` flip over a phased migration (the fix-prompt already confirmed it produces exactly one error in this codebase); single-process `uvicorn` over multi-worker Gunicorn (Render free tier is 0.1 vCPU/512MB — a second worker adds contention, not throughput).

The main risks are not "missing features" but places where a fix could look complete while leaving a narrower version of the same bug: a transactional persistence fix that doesn't account for the LangGraph checkpoint committing on its own connection before `_apply_result` runs; a mypy retrofit that silences `Tool.run`'s Protocol mismatch by widening it to `**kwargs: Any` instead of fixing it; auth landing on the backend without the frontend's API-key header shipping in the same phase (breaking the one real client); and a readiness check without an explicit timeout, which turns a slow-resuming Supabase free-tier project — the exact case H7 exists to catch — into a request pile-up against the 5-connection pool.

## Key Findings

### Recommended Stack

Every core addition for this milestone is either already a declared dependency waiting to be wired up, or a zero-new-dependency stdlib/platform feature — nothing in this stack requires a new architectural component. `pyproject.toml`/`requirements.txt` and `tsconfig.json` already have the tools; the work is retrofitting behavior, not adding libraries.

**Core technologies:**
- `slowapi` 0.1.10: per-IP rate limiting on mutating endpoints — already pinned and unimported; in-memory storage is the *correct* choice (not a compromise) for a single Render instance, since Redis-backed storage exists specifically for multi-instance consistency this project will never have
- `fastapi.security.api_key.APIKeyHeader`: shared-secret auth on mutating endpoints — zero new dependency, right-sized for a single-operator demo per `PROJECT.md`'s own Out-of-Scope decision on full user accounts
- `mypy` ^2.3.1: static type checking backend CI gate — a named strictness subset (`disallow_untyped_defs`, `warn_unused_ignores`, `no_implicit_optional`), not full `--strict`, to retrofit without a rewrite
- TypeScript `strict` + `noUncheckedIndexedAccess` (already on `typescript ~6.0.2`): compiler flags, no library — verified to produce exactly one error in this codebase today
- Native `<dialog>` + `showModal()`: accessible `ApprovalModal` — built-in focus trap, Escape-to-close, `::backdrop`, top-layer stacking, correct ARIA semantics for zero dependencies; one gotcha — conditional JSX rendering doesn't open it, it must be called imperatively

### Expected Features

**Must have (table stakes) — missing these makes the Core Value claim read as unearned:**
- Accessible approval modal (focus trap, initial focus, Escape, background `inert`) — fix-prompt M11
- Durable, sequential, gap-free trace log via a monotonic per-session sequence number (H3) — this is literally what the Core Value statement promises
- Trace entries attributed to the acting provider/model (H4) — `TraceViewer.tsx` already has dead UI waiting for this
- Structured `level` field on trace entries instead of substring-matched free text (H4/M12)
- Authentication on every mutating/irreversible endpoint (H1) — an unauthenticated approve endpoint defeats the entire HITL premise
- Per-IP/per-key rate limiting on mutating endpoints (H1)
- Readiness check reflecting real dependency health, not config presence (H7) — concretely necessary given Supabase's 7-day pause, not hypothetical
- README/docs matching current system state (fix-prompt Phase 7)

**Should have (differentiators) — reinforce the Core Value story in a live demo:**
- The one-way approval state machine's *provability* via mutation-tested regression tests (already built — worth calling out explicitly in the demo narrative)
- Honest, multi-dimensional readiness reporting (config vs. reachability vs. degraded) — cheap to build, disproportionately persuasive live (kill Supabase connectivity, watch the badge change)
- An accessible approval dialog as a *tested* capability (RTL asserting focus-trap/keyboard behavior), not just declared ARIA attributes

**Defer / explicitly out of scope (anti-features):**
- Full user accounts / OAuth-SSO / MFA — already correctly deferred in `PROJECT.md`
- Redis-backed distributed rate limiting — solves a multi-instance problem this project doesn't have
- Cryptographically signed/blockchain audit log — solves a threat model (adversarial DBA) this project doesn't have; the append-only convention already used for `ADR.md` is the right rigor level
- Full RBAC — one operator, one credential, nothing to scope
- Real-time push/streaming trace updates (websockets/SSE) — not in fix-prompt scope, violates its "do not add features" ground rule

### Architecture Approach

The existing architecture (FastAPI request/response synchronous graph execution, LangGraph interrupt/resume, Postgres via `psycopg_pool` + `langgraph-checkpoint-postgres`) doesn't need restructuring — every hardening addition attaches at an existing boundary. Auth and rate-limiting attach via router-level `Depends(...)`/middleware with zero handler-body changes. Readiness attaches to the existing `/health` vs `/health/ready` split (already structurally correct since Day 1 — ADR-009's three-way `ready`/`degraded`/`not_ready` semantics just needs real dependency dials instead of config-truthiness checks). Docker packaging is mechanical (the Dockerfile already declares a multi-stage label it doesn't yet honor).

**Major components:**
1. Persistence transaction boundary (`session_runner.py`/`repository.py`) — one Postgres transaction per `_apply_result()` outcome, plus a monotonic trace sequence number; must explicitly document the residual gap where the LangGraph checkpoint commits on its own connection *before* `_apply_result` runs (sharing a `ConnectionPool` is not sharing a transaction)
2. Auth + rate-limit middleware (`app/auth.py`, router-level `Depends`) — independent of persistence work, can run in parallel
3. Readiness endpoint (`/health/ready`) — depends on the pool's `check` callback existing first (from persistence work), needs an explicit short timeout so a slow-resuming Supabase doesn't turn readiness itself into a pile-up
4. Docker + deploy (Render backend, Vercel frontend, Supabase Postgres) — depends on readiness being real first, since `HEALTHCHECK`/Render's dashboard config need `/health` (liveness) confirmed cheap and `/health/ready` confirmed truthful

### Critical Pitfalls

1. **Transactional fix misses the checkpoint dual-write window** — wrapping `_apply_result`'s repo calls in one transaction is correct but incomplete; `graph.invoke()` commits LangGraph checkpoint state independently before that transaction runs. Document as an accepted, scoped residual gap in the ADR rather than implying full atomicity.
2. **Type-safety retrofit silences errors instead of fixing them** — the path of least resistance for `Tool.run`'s Protocol mismatch (H6) is widening it to `**kwargs: Any`, which makes mypy pass while re-hiding exactly what H6 flagged as broken. Forbid this explicitly; add `warn_return_any`/`disallow_any_generics`.
3. **Auth ships on the backend without the frontend client** — this project has exactly one client; the fix-prompt puts backend auth in Phase 5 and frontend polish in Phase 6, but the frontend's API-key header change must ship *with* Phase 5, or the deployed app breaks itself.
4. **Readiness check without a timeout becomes the reliability risk it exists to catch** — a naive `SELECT 1` without an explicit short timeout, against a slow-resuming Supabase free-tier project, piles up requests against the 5-connection pool instead of failing fast.
5. **Unmonitored keep-alive gives false confidence** — Render's spin-down and Supabase's pause are independent free-tier behaviors; a keep-alive cron is a reasonable mitigation but is itself unmonitored, and teams commonly discover it silently stopped only when the pause happens anyway. Documenting an honest cold-start UX is safer than an unverified workaround.

## Implications for Roadmap

Based on research, suggested phase structure (mapping onto `reviews/day-4-fix-prompt.md`'s existing 6-phase remediation plan):

### Phase 2: Persistence Hardening
**Rationale:** Closes the transactional/durability gap that's foundational to every later phase (readiness depends on the pool's `check` callback existing here).
**Delivers:** Atomic `_apply_result` writes, monotonic trace sequence numbers, `trace_events.provider` wired through, `httpx.Client` lifecycle fix (M2) sharing the same `lifespan` hook as the connection pool.
**Addresses:** Durable/gap-free trace log, provider attribution (table-stakes features above).
**Avoids:** The checkpoint dual-write window pitfall — must be explicitly documented as a scoped residual, not silently assumed solved.

### Phase 3: Type Safety & Testing
**Rationale:** Independent of persistence and auth work — can run in parallel. Increases confidence before the security-sensitive Phase 5 lands.
**Delivers:** mypy CI gate (named strictness subset), TypeScript `strict` + `noUncheckedIndexedAccess` flip, `Tool` Protocol actually matching implementations.
**Uses:** `mypy` ^2.3.1, existing `tsc -b` build step as the enforcement point.
**Avoids:** The "Any explosion" pitfall — explicitly forbid widening `Tool.run` to `**kwargs: Any` as the fix for H6.

### Phase 4: Trace Metadata
**Rationale:** Extends Phase 2's durability work with structured `level`/provider metadata; independent of auth/rate-limiting.
**Delivers:** Structured severity on trace entries (H4/M12), replacing substring-matched free text.
**Implements:** The audit-log best practice of structured metadata over heuristic parsing.

### Phase 5: Security & Readiness
**Rationale:** Auth + rate-limiting must land before Day 6's deploy — briefly exposing an unauthenticated approval endpoint in production is a real, if short, risk. Readiness depends on Phase 2's pool `check` callback.
**Delivers:** `APIKeyHeader` auth + `slowapi` rate limiting on mutating endpoints, a real `/health/ready` with explicit timeout, CI clean on forks with zero secrets. **Frontend API-key header wiring must ship in this same phase, not deferred to Phase 6**, per the pitfall above.
**Implements:** Router-level `Depends` auth (zero handler-body restructuring).
**Research flags:** `slowapi` exception-handler vs. `SlowAPIMiddleware` ordering has no single authoritative source — verify empirically (does a rate-limited 429 come back with correct CORS headers?) during implementation. Readiness timeout behavior needs manual verification against a real paused-then-resuming Supabase project, not just localhost.

### Phase 6: Frontend Polish & Accessibility
**Rationale:** Only after Phase 5's auth is verified end-to-end (the frontend must already be able to talk to the authenticated backend).
**Delivers:** Native `<dialog>`-based accessible `ApprovalModal` (focus trap, Escape, `inert` background), remaining frontend polish items.
**Addresses:** The accessible-modal-as-tested-capability differentiator — pair the fix with an RTL test asserting focus-trap/keyboard behavior, not just the ARIA attributes.

### Phase 7: Documentation & Deploy
**Rationale:** Final integration — Docker/deploy config only makes sense once readiness is real (Phase 5) and the frontend is polished (Phase 6).
**Delivers:** Multi-stage Dockerfile (mechanical fix to an already-labeled-but-not-actually-multi-stage build), Render `HEALTHCHECK` pointed at `/health` (liveness, never `/health/ready` — pointing it at readiness risks restart loops when a dependency like a paused Supabase is down but the process itself is fine), README/ADR/ARCHITECTURE.md truth-up, honest documentation of Render spin-down + Supabase pause cold-start UX.

### Phase Ordering Rationale

- Phase 2 (persistence) and Phase 3 (type safety) are independent of each other and of Phase 5 — they touch disjoint files and can run in parallel with each other, but Phase 5's readiness work depends on Phase 2's pool `check` callback existing first.
- Phase 5 (auth/rate-limit/readiness) must precede Phase 7 (deploy) — deploying before auth lands means a live, unauthenticated approval endpoint is briefly internet-reachable.
- Phase 6 (frontend accessibility) is sequenced after Phase 5 specifically because the frontend's auth-header change ships inside Phase 5 — Phase 6 builds on an already-authenticated client, not a separate auth migration.
- This ordering avoids the two riskiest pitfalls found: the auth/frontend deploy-skew pitfall (by pulling frontend header wiring into Phase 5) and the readiness-becomes-the-risk pitfall (by requiring Phase 2's pool infrastructure exist before Phase 5 builds readiness on top of it).

### Research Flags

Phases likely needing deeper/empirical research during planning:
- **Phase 2:** the pool's `check` callback behavior under a *real* Supabase 7-day pause (not just a local simulation) needs verification, not just implementation
- **Phase 5:** `slowapi` exception-handler vs. `CORSMiddleware`/`SlowAPIMiddleware` ordering (no single authoritative source found); `/health/ready` timeout behavior against a real paused-then-resuming Supabase; end-to-end frontend+backend auth verification before Day 6 deploy; exact `slowapi` key-function behavior behind Render's reverse proxy (`X-Forwarded-For` trust) needs verification against the real deployed environment, not localhost

Phases with standard, well-documented patterns (skip deep research):
- **Phase 3:** mypy/TS-strict retrofit patterns are well-established and already partially verified against this exact codebase (one known TS error, existing Protocol-based tool interface)
- **Phase 4:** trace metadata (add columns, wire through nodes, display in UI) is mechanical, not novel
- **Phase 6:** native `<dialog>` usage in React 19 is well-documented; the one gotcha (imperative `showModal()` call vs. conditional JSX) is already identified

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM-HIGH | Core choices (`slowapi`, `APIKeyHeader`, mypy, `<dialog>`) well-documented and cross-verified against PyPI/official docs; no Context7/official-docs MCP available this session for the ecosystem-survey parts, so those are web-search-corroborated (MEDIUM) while version numbers pulled directly from PyPI/psycopg docs are HIGH |
| Features | HIGH | Directly grounded in `PROJECT.md`'s Core Value statement and `reviews/day-4-fix-prompt.md`'s existing scope, cross-checked against general HITL-product conventions — little ambiguity |
| Architecture | MEDIUM | Patterns (transactional boundary, router-level auth, liveness/readiness split, deploy topology) are well-established and grounded directly in this repo's actual code; a few specifics (slowapi/CORS middleware ordering, exact psycopg `check` behavior under Supabase's specific pause mechanics) have no single authoritative source and need empirical verification during implementation |
| Pitfalls | MEDIUM-HIGH | The most load-bearing pitfall (checkpoint dual-write window) is grounded directly in this repo's own `session_runner.py`/`db.py`/`repository.py` code, not just general advice; the free-tier-specific pitfalls (Render spin-down, Supabase pause) are corroborated across official docs plus multiple independent community sources |

**Overall confidence:** MEDIUM — research is thorough and triangulated across independent sources, and several claims are grounded directly in this repo's own code rather than generic advice. The MEDIUM rating reflects that a handful of specific interaction behaviors (middleware ordering, free-tier pause/resume timing) have no single authoritative source and are flagged for empirical verification during implementation, not weaknesses in the research itself.

### Gaps to Address

- `slowapi` exception-handler vs. `SlowAPIMiddleware`/`CORSMiddleware` registration ordering: verify empirically during Phase 5 implementation (check that a 429 response carries correct CORS headers)
- psycopg_pool's `check` callback exact behavior under a real Supabase 7-day pause: test directly against a paused project during Phase 2/5, not just inferred from docs
- Render dashboard health-check configuration (outside the codebase, a platform UI setting): verify during Phase 7 deploy that it's pointed at `/health`, not `/health/ready`
- Whether to actively fight free-tier cold starts (keep-alive cron) or accept and document them: a product decision for roadmap/requirements definition, not resolved by this research — leaning toward documenting an honest cold-start UX over an unmonitored keep-alive mechanism, per the pitfalls findings
- Whether `allow_credentials=True` in CORS config should be dropped once auth moves to header-based `X-API-Key`: a decision for the Phase 5 auth ADR

## Sources

### Primary (HIGH confidence)
- PyPI registry JSON API — `slowapi`, `mypy` current version numbers
- psycopg official docs — `ConnectionPool` `check=` parameter, `open=True` deprecation
- Supabase official docs — free-tier 7-day pause behavior
- This repository's own code (`session_runner.py`, `repository.py`, `db.py`, `api.ts`, `ApprovalModal.tsx`, `PROJECT.md`, `reviews/day-4-review.md`, `reviews/day-4-fix-prompt.md`) — read directly, not inferred

### Secondary (MEDIUM confidence)
- Web search across 3+ independent sources per topic (FastAPI auth/rate-limiting patterns, Kubernetes-derived liveness/readiness conventions, Render/Vercel/Supabase free-tier deploy write-ups, mypy/TypeScript-strict retrofit practitioner reports, WAI-ARIA dialog pattern guidance, HITL agent-product approval-UX conventions)

### Tertiary (LOW confidence)
- General enterprise agent-governance / compliance-audit-log framing (cryptographic provenance chains, RBAC) — explicitly assessed as not applicable to this project's scope, not adopted, retained only to document why it was rejected as an anti-feature

---
*Research completed: 2026-08-25*
*Ready for roadmap: yes*
