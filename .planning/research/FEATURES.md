# Feature Research

**Domain:** Human-in-the-loop AI agent orchestration copilot (LangGraph-based, single-operator portfolio demo)
**Researched:** 2026-08-25
**Confidence:** MEDIUM

Scope note: this research is deliberately narrow to what Days 5-7 (`reviews/day-4-fix-prompt.md` Phases 2-7) still need — approval-dialog UX, trace/audit-log durability, minimum-viable auth, and honest readiness checks — evaluated against how comparable HITL agent products (Devin, Cursor agent mode, GitHub Copilot Workspace, AutoGPT-style tools) and general platform conventions (WAI-ARIA, Kubernetes probe semantics, FastAPI rate-limiting ecosystem) handle the same four surfaces. Findings are synthesized from web search (MEDIUM confidence — no official Devin/Cursor engineering-blog access, so agent-specific claims are triangulated across secondary sources) plus this repo's own already-validated architecture (HIGH confidence — read directly from `PROJECT.md` and the fix-prompt).

## Feature Landscape

### Table Stakes (Users Expect These)

Features a reviewer/demo-watcher assumes exist. Missing these makes the "human-in-the-loop" and "production-grade reliability" claims in `PROJECT.md`'s Core Value read as unearned.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Accessible approval modal (focus trap, initial focus, Escape, background inert) | Every HITL product's whole value proposition is "the human decision is real" — a modal a screen reader/keyboard user can't operate, or that leaks focus to the page behind it, contradicts that on the one dialog in the app that gates an irreversible action (fix-prompt M11) | LOW-MEDIUM | Two credible paths: native `<dialog>` + `showModal()` (gets focus trap, `::backdrop`, and Escape-closes for near-free — verify Escape behavior is what you want, since accidental dismissal of an approval prompt is a real hazard per M11's own text) or hand-rolled trap + `inert` on the background. Given the project already declared `role="dialog" aria-modal="true"` and just needs the *behavior* to catch up, extending the existing component is lower-risk than a `<dialog>` rewrite this late in the build. |
| Diff-style / full-detail action disclosure before approval | Cross-agent convergence (Devin, Copilot Workspace, general HITL guidance): "show the exact action, target, and content... hide nothing the user is authorizing" | Already built | The approval modal already surfaces the pending action's tool/args per Day 3-4 scope — this is a confirm-it-still-holds item, not new work. |
| Durable, sequential, gap-free trace log | The project's own Core Value statement makes this literally the product; H3's count-based diff bug (silent drop/duplication) is exactly the failure mode that breaks it | MEDIUM | Requires the fix-prompt's monotonic per-session sequence number (H3) — this is not optional polish, it's the mechanism that makes "durable" true rather than aspirational. |
| Trace entries attributed to the specific provider/model that acted | ADR-002's failover story has no observable payoff without it; `TraceViewer.tsx` already has dead UI for this (H4) | LOW | `trace_events.provider` already has a column and a UI branch; H4 is "wire the plumbing," not new design. |
| Structured severity/tone on trace entries, not substring-matched free text | General audit-log guidance: log entries need reliable structured metadata, not heuristic parsing of a human-readable `detail` string that can accidentally contain trigger words like "retry" | LOW | H4/M12 already scope a `level` field — this generalizes the audit-logging best practice ("capture reasoning/outcome as structured metadata") into a concrete column. |
| Authentication on every mutating/irreversible endpoint | An unauthenated `POST /approvals/{id}/approve` defeats the entire HITL premise — this is the single most damaging credibility gap a reviewer could find (H1) | MEDIUM | Shared-secret API key header (`X-API-Key` or `Authorization: Bearer`) checked via a FastAPI dependency is the right-sized MVP; see Differentiators/Anti-Features below for why this beats the alternatives at this scope. |
| Per-IP or per-key rate limiting on mutating endpoints | Table stakes for any publicly reachable endpoint that can trigger LLM calls or approve irreversible actions, regardless of HITL-specific expectations | LOW | `slowapi` is already a declared, unused dependency (H1) — in-memory storage is explicitly the recommended default for single-instance deployments exactly like this one, so no Redis is needed. |
| Readiness check that reflects real dependency health, not config presence | The project's own free-tier constraint (Supabase pauses after 7 days idle) makes this concretely, not hypothetically, necessary — the current check would report `ready` against a paused database (H7) | LOW-MEDIUM | Kubernetes-derived convention applies directly even without K8s: liveness-equivalent (`/health`) stays a lightweight "process is up" check; readiness-equivalent (`/health/ready`) does a real `SELECT 1` with a short timeout. Keep the existing three-way `ready`/`degraded`/`not_ready` semantics (ADR-009) — this is refining an existing contract, not replacing it. |
| Separation of liveness-style and readiness-style checks | Universal platform convention (Kubernetes probes, but the pattern predates and outlives K8s specifically) — conflating "is the process up" with "can it serve a real request" causes exactly the two different failure-handling behaviors you don't want to conflate (restart vs. hold traffic) | Already partially built | The project already has `/health` and `/health/ready` as separate endpoints (Day 1) — H7 is "make the second one honest," not "add the split." |
| README/docs that match current system state | Not agent-specific, but a portfolio-demo table stake: a reviewer who reads "Day 1 of a 7-day build" while looking at a Day-4+-complete system loses trust in every other claim in the repo | LOW | Fix-prompt Phase 7 (L9-L11) already scopes this precisely. |

### Differentiators (Competitive Advantage)

Features that set this apart from a typical bootcamp/tutorial HITL demo, directly reinforcing the Core Value statement.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| One-way approval state machine that provably cannot be re-entered or bypassed | Most HITL tutorial demos treat "approve" as a boolean flag toggled in place; this project already models it as `pending → approved/rejected → executed`, which is closer to how production agent platforms (per HITL research: "action manifest," explicit interrupt/resume protocols) actually reason about irreversibility | Already built | The differentiator is *provability* — the mutation-tested regression tests for C4 (session-wedging on exception) are what let you credibly claim this holds under failure, not just under the happy path. Worth calling out explicitly in the README/demo narrative. |
| Trace log that explains *why*, not just *that* | General agent-audit-log research: "the raw log shows what happened, but the reasoning trace explains why the agent thought it was correct" — most portfolio HITL demos only log actions, not planner rationale | LOW (mostly already present via planner trace entries) | Already substantially covered by the existing planner→delegate→observe trace entries; H4/M12's provider+level fields extend this into more precisely structured metadata, which is the differentiator over an unstructured log line. |
| Honest, multi-dimensional readiness reporting (config vs. reachability vs. degraded-but-serving) | Most single-operator demos ship a `/health` that always returns 200; distinguishing "misconfigured" from "unreachable" from "degraded-but-functional" (ADR-009's 3-way semantics) is closer to how real platforms reason about health, and it's directly demonstrable live (kill Supabase connectivity, watch the badge change) | LOW (H7 already scopes exactly this) | This is cheap to build (it's already 80% scoped) and disproportionately persuasive in a live demo — showing a real dependency failure downgrade beats describing it in a README. |
| An accessible approval dialog as a demonstrated, tested capability (not just declared ARIA attributes) | Almost no portfolio AI-agent demo ships RTL tests asserting focus-trap and keyboard behavior on its approval gate; fix-prompt M11 already requires this | MEDIUM | The differentiator is the *test*, not just the behavior — "focus moves into the dialog, Tab cycles within it, Escape does X" as an asserted RTL test is a credible, unusual signal of rigor for a solo portfolio build. |
| Provider-failover visibility surfaced end-to-end in the UI | Differentiates from single-provider demos; ADR-002 + H4 together mean a reviewer can watch a live failover happen and see it attributed in the trace, not just read about it in an ADR | LOW (H4 is the only remaining gap) | Already committed to in the fix-prompt; worth foregrounding in the demo script once H4 lands. |

### Anti-Features (Commonly Requested, Often Problematic — Explicitly Out of Scope Here)

Features that a "real" HITL product might have, but that would be scope creep, false rigor, or actively counter to this project's stated boundaries.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Full user accounts / Supabase Auth / OAuth-SSO login | General best-practice guidance (and this research's own findings) says API keys should be "paired with OAuth2, not a replacement," and real admin dashboards "favor full user accounts via SSO layered with MFA" | `PROJECT.md` has already explicitly deferred this (Out of Scope) as disproportionate for a single-operator demo; adding it now is a scope-boundary violation, not a gap — it multiplies surface area (session management, password/token flows, user table, RBAC) for a system with exactly one legitimate user | Shared-secret API key header via a FastAPI dependency, checked with `secrets.compare_digest` to avoid timing leaks; document in an ADR (as H1 already requires) exactly what this gives up (no per-user audit attribution, no revocation-without-redeploy) so the tradeoff is explicit, not silently assumed |
| Redis-backed distributed rate limiting | "Best practice" articles on rate limiting default to recommending Redis for production credibility | The project is a single Render instance by explicit constraint (Out of Scope: horizontal scaling) — Redis adds a paid/free-tier-risk dependency and operational surface for a distributed-consistency problem that doesn't exist at one instance | `slowapi`'s in-memory storage, which its own docs describe as the correct choice for exactly this deployment shape; note in the ADR that this is a deliberate single-instance choice, not an oversight |
| Cryptographically signed / blockchain-anchored / tamper-proof audit log | Some enterprise-agent-governance research recommends cryptographic provenance chains and immutable ledgers for regulated audit trails | This is a portfolio demo, not a regulated financial or healthcare system — the actual problem the trace log needs to solve (per Core Value) is completeness and explainability under concurrent/failure conditions, which the monotonic-sequence-number fix (H3) already solves; cryptographic signing solves a threat model (an adversarial DBA tampering with rows) this project doesn't have | The append-only convention already in use for `ADR.md` and forward-only migrations is the right level of rigor for this scope; a Postgres sequence + no `UPDATE`/`DELETE` grants on `trace_events` is a credible "durable and hard to accidentally corrupt" story without inventing a ledger |
| Full RBAC / per-action permission scoping | "Least privilege" guidance generally recommends scoping every credential narrowly by role/endpoint | There is exactly one operator and one credential; building a permissions model for a population of one is speculative complexity with no scenario that exercises it, and it would need its own tests/docs to not be dead code | A single shared secret authorizes all mutating endpoints; if this were ever handed to a second person, that's the trigger to revisit, not something to pre-build |
| Real-time push/streaming trace updates (websockets/SSE) | Modern agent UIs (and some AutoGPT-style tools) stream token-by-token or event-by-event | Not in the fix-prompt's remaining scope, adds meaningful complexity (connection lifecycle, reconnection, backpressure) for a demo where polling the trace endpoint is indistinguishable to a viewer at human-perceptible latency, and risks introducing exactly the kind of new-feature scope the fix-prompt explicitly forbids ("Do not add features") | Keep the existing fetch/poll pattern; if it feels slow in the live demo, tighten the poll interval rather than adding a new transport |
| MFA / passkeys / hardware-key auth | Reasonable for any real admin login | Layering MFA onto a single shared-secret API key used by its one operator doesn't reduce the actual risk (the key itself is still the single point of compromise) and isn't part of what H1 scopes | If key compromise is a real worry, the mitigation is a rotatable secret plus not committing it to source (already presumably true) — not an MFA flow with no second factor to attach to |
| Chain-of-custody / signed reasoning traces for regulatory compliance framing | Enterprise agent-governance sources (NIST AI RMF-adjacent) frame audit trails as compliance artifacts | This project is explicitly a portfolio demonstration of engineering rigor, not a compliance deliverable — framing the trace log as "regulatory audit trail" invites a credibility mismatch when a reviewer asks what regulation it satisfies | Frame the trace log's value correctly in docs: durability and explainability for debugging/trust, not compliance |

## Feature Dependencies

```
Approval state machine (already built, C4-hardened)
    └──requires──> Transactional persistence (H2)
                       └──requires──> Trace sequence numbers (H3)

Accessible approval modal (M11)
    └──independent of──> Auth (H1) and Readiness (H7)
                          (can be built/tested in isolation)

Trace provider attribution (H4)
    └──requires──> TraceEvent.provider field threaded through planner/finalize nodes
Trace structured level/tone (M12)
    └──requires──> TraceEvent.level field (same migration as H4)
    └──enables──> Removal of TraceViewer's substring-matching heuristic

Auth (H1: shared-secret API key)
    └──requires──> Rate limiting (H1: slowapi) to be meaningful
                       (auth without rate limiting still allows a single
                       leaked/guessed key to be brute-forced or abused)
    └──should precede──> Deploy to Render+Vercel (Day 6)
                       (deploying an unauthenticated approval endpoint
                       publicly, even briefly, defeats the point)

Readiness check reflecting real DB health (H7)
    └──requires──> Pool lifecycle fix (M1: check= callback, lifespan close)
                       (a readiness check that dials a pool prone to handing
                       out dead connections will flap/false-negative)
    └──should precede──> Deploy to Render+Vercel (Day 6)
                       (this is precisely what catches Supabase's 7-day
                       pause in production, per PROJECT.md's own framing)

Docs truth-up (Phase 7)
    └──depends on──> All of the above being actually done
                       (docs describe real state; writing them first would
                       just be re-committing the current staleness problem)
```

### Dependency Notes

- **Approval state machine requires transactional persistence:** H2's atomicity fix is what makes the state machine's guarantees ("can never be bypassed, re-entered, or silently skipped," per `PROJECT.md`'s Core Value) actually true under partial failure, not just under the happy path. Building the accessible modal (M11) on top of a still-non-atomic backend would produce a UI that's honest about state it can't actually guarantee.
- **Auth should precede deploy, not follow it:** the fix-prompt already sequences H1 in Phase 5, before Day 6's Docker/deploy — this research confirms that ordering is correct, since deploying `POST /approvals/{id}/approve` unauthenticated to a public Render URL, even for a few hours between phases, is a real (if brief) exposure of the one action the whole HITL design exists to gate.
- **Readiness fix depends on pool lifecycle fix:** H7's `SELECT 1` check is only trustworthy if the connection pool itself doesn't silently hand back a dead connection (M1's `check=` callback) — doing H7 without M1 risks the readiness check itself becoming a source of false negatives/flapping, which is the same anti-pattern general K8s-probe guidance warns against for liveness (don't let infrastructure noise trigger the wrong response).
- **Rate limiting depends on auth to be meaningful:** limiting by bare IP (the `slowapi` default `get_remote_address`) is a reasonable baseline, but once H1's API key exists, keying the limiter by the authenticated identity rather than IP is a cheap upgrade this research surfaced (best practice: "consider using API keys... instead of just IP addresses") and worth doing in the same phase rather than as a follow-up.
- **Trace provider/level fields share one migration:** H4 and M12 both add columns to `trace_events` and are already scoped together in the fix-prompt — no new dependency found here, just confirming the existing phase grouping is correct.

## MVP Definition

Given this is a remediation/hardening pass on an already-scoped system (not a green-field MVP decision), "Launch With" below maps to what fix-prompt Phase 5-6 already commits to, reframed by what a demo-credibility bar actually requires.

### Launch With (Days 5-6 — non-negotiable for demo credibility)

- [ ] Authenticated approval/mutating endpoints (shared-secret API key) — without this, the HITL premise is falsifiable by anyone with the URL
- [ ] Rate limiting on mutating endpoints (`slowapi`, in-memory) — table stakes for any public endpoint, cheap given the dependency already exists
- [ ] `/health/ready` dials the real database — this is the concrete, demonstrable proof that "readiness" means something, and it's what catches the Supabase 7-day pause this project already knows is coming
- [ ] Transactional persistence + sequenced trace log (H2/H3) — the trace log *is* the product per Core Value; without this the durability claim is aspirational
- [ ] `trace_events.provider` and `level` wired end-to-end (H4) — dead UI for a claimed differentiator (failover visibility) undercuts the differentiator
- [ ] Accessible approval modal (focus trap, Escape, inert background) with RTL tests (M11) — the one dialog gating an irreversible action must not be a keyboard/screen-reader trap
- [ ] Docs truth-up (Phase 7) — a stale "Day 1" status line undermines every other claim on first read

### Add After Validation (Day 6-7, once core hardening is verified)

- [ ] Docker/deploy to Render + Vercel free tiers — deliberately sequenced after auth/readiness so nothing insecure or dishonest-about-health goes live even briefly
- [ ] Final demo-readiness/polish pass (Day 7) — includes verifying the live failover and readiness-degradation scenarios are actually demonstrable on the deployed instance, not just in local tests

### Future Consideration (explicitly not this milestone, possibly never for this project)

- [ ] Full user accounts / SSO / MFA — only relevant if this ever needs more than one legitimate operator
- [ ] Redis-backed distributed rate limiting — only relevant if horizontal scaling ever gets un-deferred
- [ ] Cryptographically signed/immutable audit log — only relevant if this project ever needed to satisfy an actual regulatory audit, which it doesn't
- [ ] Real-time streaming trace updates — nice-to-have UX polish with no bearing on the correctness/trust claims the project is actually making

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Auth on mutating endpoints (H1) | HIGH | MEDIUM | P1 |
| Rate limiting (H1) | MEDIUM | LOW | P1 |
| Honest `/health/ready` (H7) | HIGH | LOW-MEDIUM | P1 |
| Transactional persistence (H2) | HIGH | MEDIUM | P1 |
| Durable trace sequencing (H3) | HIGH | MEDIUM | P1 |
| Provider attribution in trace (H4) | MEDIUM | LOW | P1 |
| Structured trace level/tone (H4/M12) | MEDIUM | LOW | P1 |
| Accessible approval modal (M11) | HIGH | MEDIUM | P1 |
| Docs truth-up (Phase 7) | MEDIUM | LOW | P1 |
| Pool lifecycle / `check=` callback (M1) | MEDIUM | LOW | P1 (blocks H7) |
| Docker hardening (M9) | MEDIUM | LOW-MEDIUM | P2 |
| CI fork-safety (H8) | MEDIUM | MEDIUM | P2 |
| Live failover/degradation demo script | HIGH (for portfolio narrative) | LOW | P2 |
| Full user accounts / SSO | LOW (at this scope) | HIGH | P3 (explicitly deferred) |
| Redis-backed rate limiting | LOW (at this scope) | MEDIUM | P3 (explicitly deferred) |
| Cryptographic/immutable audit log | LOW (at this scope) | HIGH | P3 (explicitly deferred) |
| Real-time streaming trace | LOW-MEDIUM | MEDIUM | P3 |

**Priority key:**
- P1: Must have — already scoped in fix-prompt Phases 2-7, confirmed table-stakes by this research
- P2: Should have — supports the demo narrative or long-term CI health but isn't a trust-breaking gap if slightly late
- P3: Explicitly deferred anti-features for this project's scope — not to be built without a scope-boundary decision reversing `PROJECT.md`'s Out of Scope section

## Competitor Feature Analysis

| Feature | Devin | Cursor agent mode / Copilot Workspace | Agent Ops approach |
|---------|-------|----------------------------------------|---------------------|
| Approval/review mechanism | Separate reviewer agent critiques the writing agent's work in a closed loop; human involvement is opt-in for edge cases | Plan-then-execute: visible, editable plan surfaced before code changes are applied; diff-based review is the default confirm step | Real one-way state machine (`pending → approved/rejected → executed`) with an explicit human approval gate on every action classified as needing it — closer to "human-in-the-loop" (every action gated) than Devin's "human-on-the-loop" (monitor can interrupt) design; this is a deliberate, defensible choice for a demo whose whole point is showing the gate work, not autonomy |
| Action disclosure | Diff of code changes shown for review | Full plan + diff shown before commit | Approval modal already surfaces the pending tool call and its arguments; needs the accessibility fix (M11) to be a credible implementation of the same disclosure principle |
| Audit/trace visibility | Not publicly documented in detail | Plan history is visible in the UI as a first-class object | Full trace log across planner/delegate/tool-call/observe/decide-next is already more granular than what's publicly documented for either competitor — this is a genuine differentiator once H3/H4/M12 make it durable and structured |
| Auth model | Enterprise SSO (multi-tenant SaaS) | IDE-integrated, uses the user's existing editor/account session | Not comparable at this scope — both competitors are multi-tenant commercial products with real user bases; a shared-secret API key is the right-sized analog for a single-operator demo, not an attempt to replicate enterprise SSO |
| Health/readiness signaling | Not applicable (SaaS uptime is Devin's problem, not surfaced per-user) | Not applicable | Readiness endpoint with real dependency checks and 3-way semantics is arguably more transparent than either commercial product exposes to its own users — a differentiator specific to this project's "show your reliability work" portfolio framing |

## Sources

- [Building an Accessible Widget: WAI-ARIA Modal Alert Dialogs (Deque)](https://www.deque.com/blog/aria-modal-alert-dialogs-a11y-support-series-part-2/)
- [Alert Dialog Example | WAI-ARIA Authoring Practices (W3C APG)](https://www.w3.org/WAI/ARIA/apg/patterns/alertdialog/examples/alertdialog/)
- [Accessible Modal Dialogs: Focus Trapping and Screen Reader Support (TestParty)](https://testparty.ai/blog/modal-dialog-accessibility)
- [How to Build Accessible Modals with Focus Traps (UXPin)](https://www.uxpin.com/studio/blog/how-to-build-accessible-modals-with-focus-traps/)
- [What Is Human-in-the-Loop (for AI Agents)? (CopilotKit)](https://www.copilotkit.ai/learning/what-is-human-in-the-loop)
- [Human-in-the-loop patterns for AI agents in Jira (Atlassian)](https://www.atlassian.com/software/jira/guides/agentic-engineering/human-in-the-loop)
- [Human-in-the-Loop Patterns for High-Stakes AI Agent Decisions (DEV Community)](https://dev.to/omnithium/human-in-the-loop-patterns-for-high-stakes-ai-agent-decisions-1fg6)
- [Plans vs tasks: how AI agents think before they act (CrabTalk)](https://crabtalk.ai/blog/plans-vs-tasks-agent-design)
- [Human-in-the-Loop AI Agents: Implementation Patterns (BuildMVPFast)](https://www.buildmvpfast.com/blog/human-in-the-loop-ai-agents-implementation-patterns-2026)
- [Human in the loop · Collab AI UX Pattern (AI UX Playground)](https://aiuxplayground.com/pattern/human-in-the-loop/)
- [Auditing and Logging AI Agent Activity: A Guide for Engineers (LoginRadius)](https://www.loginradius.com/blog/engineering/auditing-and-logging-ai-agent-activity)
- [MCP Audit Logging: Tracing AI Agent Actions for Compliance (Tetrate)](https://tetrate.io/learn/ai/mcp/mcp-audit-logging)
- [AI Agent Compliance & Governance in 2025 (Galileo)](https://galileo.ai/blog/ai-agent-compliance-governance-audit-trails-risk-management)
- [AI Agent Audit Trails Explained (miniOrange)](https://www.miniorange.com/blog/ai-agent-audit-trail/)
- [Agent Decision Audit and Explainability (FINOS AIR Governance Framework)](https://air-governance-framework.finos.org/mitigations/mi-21_agent-decision-audit-and-explainability.html)
- [API Key Management Best Practices for Multi-Tenant Apps (Corsair)](https://corsair.dev/blog/api-key-management-best-practices-multi-tenant-apps)
- [Service Account Authentication Best Practices: From API Keys to OAuth 2.0 (SSOJet)](https://ssojet.com/blog/service-account-authentication-best-practices-api-keys-oauth)
- [Best practices for REST API security: Authentication and authorization (Stack Overflow Blog)](https://stackoverflow.blog/2021/10/06/best-practices-for-authentication-and-authorization-for-rest-apis/)
- [API Security Best Practices: A Developer's Guide (Postman Blog)](https://blog.postman.com/api-security-best-practices/)
- [Liveness, Readiness, and Startup Probes (Kubernetes docs)](https://kubernetes.io/docs/concepts/workloads/pods/probes/)
- [How to Implement Health Checks That Distinguish Between Liveness and Readiness (OneUptime)](https://oneuptime.com/blog/post/2026-02-09-health-checks-liveness-vs-readiness/view)
- [Kubernetes Liveness & Readiness Probes Best Practices (Beefed.ai)](https://beefed.ai/en/kubernetes-liveness-readiness-probes-best-practices)
- [Kubernetes best practices: setting up health checks with readiness and liveness probes (Google Cloud Blog)](https://cloud.google.com/blog/products/containers-kubernetes/kubernetes-best-practices-setting-up-health-checks-with-readiness-and-liveness-probes)
- [SlowApi Documentation](https://slowapi.readthedocs.io/)
- [5 FastAPI Rate-Limiter Designs That Actually Scale (Medium)](https://medium.com/@connect.hashblock/5-fastapi-rate-limiter-designs-that-actually-scale-49e467854b11)
- [Using SlowAPI in FastAPI: Mastering Rate Limiting Like a Pro (Medium)](https://shiladityamajumder.medium.com/using-slowapi-in-fastapi-mastering-rate-limiting-like-a-pro-19044cb6062b)
- `D:\agent-ops\.planning\PROJECT.md` (project scope, Core Value, Out of Scope boundaries) — HIGH confidence, primary source
- `D:\agent-ops\reviews\day-4-fix-prompt.md` (remaining Phase 2-7 findings: H1-H8, M1-M12, L-series) — HIGH confidence, primary source

---
*Feature research for: Human-in-the-loop AI agent orchestration copilot, Days 5-7 remediation scope*
*Researched: 2026-08-25*
