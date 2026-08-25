# Agent Ops

## What This Is

Agent Ops is a multi-agent orchestration copilot: a planner → delegate →
tool-call → observe → decide-next LangGraph agent that runs real tasks
(calculator, notes, web search) behind a human-in-the-loop approval gate,
with automatic LLM provider failover (Gemini primary, OpenRouter `:free`
fallback) and a full trace log of every decision. It's a solo, public 7-day
portfolio build (`MASTER_PROMPT.md`) demonstrating production-grade agent
reliability patterns, not a commercial product.

## Core Value

The trace log is the product: every planner decision, tool call, retry, and
approval must be durably recorded and explainable, and the human-in-the-loop
approval gate must be a real one-way state machine that can never be
bypassed, re-entered, or silently skipped. If those two things don't hold,
nothing else about the build matters.

## Requirements

### Validated

<!-- Shipped and confirmed valuable via a full code review of Days 1-4. -->

- ✓ FastAPI backend with health/readiness endpoints — Day 1
- ✓ Provider-agnostic LLM interface: Gemini primary + OpenRouter automatic
  failover, with correct exception-translation boundary — Day 2
- ✓ Planner→delegate→tool-call→observe→decide-next LangGraph agent graph,
  three tools (calculator, notes, web search) — Day 2
- ✓ HITL approval as a real state machine (pending→approved/rejected→executed)
  using LangGraph interrupt/resume — Day 3
- ✓ Supabase Postgres persistence (sessions, messages, trace_events,
  pending_actions) + `langgraph-checkpoint-postgres` for durable graph state
  — Day 3
- ✓ React+TS+Vite+Tailwind frontend: chat panel, approval modal, trace
  viewer, session list/detail — Day 4
- ✓ GitHub Actions CI: lint+test+build for backend and frontend — Day 1
- ✓ Four Day 1-4 critical correctness defects (Gemini-only deploy 500s,
  unbounded calculator DoS, a successful final step reported as failed,
  exceptions permanently wedging a session) found by a full code review and
  fixed with mutation-tested regression tests — Phase 1 remediation, `f47d007`

### Active

<!-- Remaining scope: Days 5-7 per MASTER_PROMPT.md, restructured around
     reviews/day-4-fix-prompt.md's remaining 6 phases, which decompose most
     of that remaining work with more precision than re-deriving it. -->

- [ ] Session/trace persistence is transactional and durable — no partial
      writes leave a session unrecoverable, trace sequencing never silently
      drops or duplicates events, `trace_events.provider` is actually written
      (fix-prompt Phase 2: H2, H3, H4, M1, M3, L12-14)
- [ ] Type safety enforced in CI — mypy on the backend, TypeScript `strict`
      on the frontend, and the `Tool` Protocol actually matches what the
      implementations do (fix-prompt Phase 3: H5, H6, M5, L19)
- [ ] Every tool failure is caught and logged at the adapter boundary with no
      leaked resources (`httpx.Client`, narrow exception catches) (fix-prompt
      Phase 4: M2, M6, M7)
- [ ] The approval gate and mutating endpoints are authenticated and
      rate-limited, `/health/ready` dials its real dependencies instead of
      checking config strings, and CI runs cleanly on a fork with zero
      secrets (fix-prompt Phase 5 — this is Day 5/6's security & hardening
      scope: H1, H7, H8, M9, M10, L16)
- [ ] The approval modal is a real accessible dialog (focus trap, Escape,
      `inert` background) and the remaining frontend polish items are closed
      (fix-prompt Phase 6: M11, M12, L2-8)
- [ ] Documentation reflects actual current state — README leads with the
      problem/solution instead of the stale "Day 1" status line, new
      append-only ADRs record every fix above, `ARCHITECTURE.md` gets a "Day
      4.5 amendments" section (fix-prompt Phase 7 + Day 5's README rewrite)
- [ ] Backend and frontend are containerized and deployed to Render + Vercel
      on free tiers, with production env vars configured and verified — Day 6
- [ ] Final review/polish pass and demo-readiness check — Day 7

### Out of Scope

- Supabase Auth / full user accounts — considered for Day 4, explicitly
  deferred; a shared-secret API key is the chosen auth mechanism for the
  approval-gate fix instead (lighter weight, sufficient for a
  single-operator portfolio demo)
- Horizontal scaling / multi-instance deployment — a single Render instance
  is sufficient for a portfolio demo; this is a hard scope boundary, not an
  oversight
- Any paid infrastructure or tier, for any service — hard constraint from
  `MASTER_PROMPT.md`; anything with paid-tier risk must be flagged and
  stopped on, never silently used

## Context

- This is a solo, 7-day public portfolio build (`MASTER_PROMPT.md`)
  demonstrating production-grade AI agent orchestration: provider failover,
  a real HITL approval state machine, full trace/observability, and now,
  via the Day-4 review cycle, demonstrated rigor through a full
  code-review-and-fix pass.
- `reviews/day-4-review.md` is a full review of everything built through Day
  4 (4 Critical, 8 High, 12 Medium, 22 Low findings, tag `day-4-complete`).
  `reviews/day-4-fix-prompt.md` is the 7-phase remediation plan derived from
  it. Phase 1 (the four Critical findings) is fixed and committed
  (`f47d007`); a follow-up review (`REVIEW.md`) caught and fixed one
  residual gap in the C4 fix before it was committed. Phases 2-7 are what
  the Active requirements above track.
- The project's own established convention (`MASTER_PROMPT.md` §2.4) is a
  self-review gate before every deploy: the `reviewer` subagent reviews the
  diff, writes `REVIEW.md`, and real findings get fixed before shipping —
  this is not a one-time thing, it applies to every remaining phase too.
- Free-tier constraints shape everything: Gemini + OpenRouter `:free`
  models, Supabase free Postgres (pauses after 7 days of inactivity — this
  is exactly what H7's readiness-check fix needs to detect), Render free web
  service, Vercel free static hosting.

## Constraints

- **Tech stack**: FastAPI/Python 3.11 backend, React 19+TS+Vite+Tailwind
  frontend, LangGraph 1.2.11 agent orchestration, Supabase Postgres+pgvector
  — locked in from Day 1-2 ADRs, not to be changed
- **Budget**: free-tier only across every service (Gemini, OpenRouter,
  Supabase, Render, Vercel) — a hard constraint from `MASTER_PROMPT.md`
- **Timeline**: originally a 7-day build; currently mid-flight past Day 4
  with a review-remediation detour before Days 5-7 resume
- **Process**: `ADR.md` is append-only, migrations are forward-only, and
  every deploy is gated by a self-review (reviewer subagent → `REVIEW.md` →
  fix real findings before shipping) — established Day 1-4 conventions, not
  to be bypassed for the remaining phases

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Fixed the C4 residual gap (`add_message`/`mark_pending_action_executed` left unwrapped) inline during remediation rather than deferring it | It reproduced the exact defect C4 was meant to close, just one statement later — leaving it open would make the "C4 fixed" claim false | ✓ Good |
| Restructured the remaining Day 5-7 roadmap around the existing `reviews/day-4-fix-prompt.md`'s 6 remaining phases, rather than re-deriving scope from `MASTER_PROMPT.md` alone | The fix-prompt already decomposes almost all remaining hardening/security/docs work with more precision, and Phase 5 already *is* most of Day 5's stated scope (rate limiting, H1 auth) | — Pending, to be validated once the roadmap is built |

---
*Last updated: 2026-08-25 after Phase 1 review-remediation commit (`f47d007`), before roadmap creation*
