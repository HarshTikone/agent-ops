# Pitfalls Research

**Domain:** Retrofitting transactional persistence, type safety, auth/rate-limiting, real readiness checks, free-tier deployment, and accessibility onto an existing LangGraph-based HITL agent orchestrator (Agent Ops, Days 5-7 / fix-prompt Phases 2-7)
**Researched:** 2026-08-25
**Confidence:** MEDIUM (web sources cross-checked against official docs — psycopg.org, GitHub Docs, Supabase Docs — plus direct grounding against this repo's actual code: `session_runner.py`, `repository.py`, `db.py`, `ApprovalModal.tsx`, `ci.yml`)

This file intentionally does not repeat findings already caught and being fixed per `reviews/day-4-review.md` / `reviews/day-4-fix-prompt.md` (H1-H8, M1-M12, C1-C4). It sharpens *how those fixes commonly go wrong mid-flight* — the second-order mistakes teams make while implementing exactly this kind of remediation.

## Critical Pitfalls

### Pitfall 1: The transaction fix stops at the repo layer and misses the checkpointer dual-write

**What goes wrong:**
H2's fix wraps `_apply_result`'s 2-4 `repo.*` calls in one explicit transaction. That's correct and necessary — but it's easy to declare victory there and miss that `graph.invoke()` (called just before `_apply_result` in both `start_session_run` and `resume_session_run`) already committed the LangGraph checkpoint state through `PostgresSaver`, on its **own connection checked out from the same pool**, *before* `_apply_result` even runs. Even though `get_checkpointer()` and `get_db_pool()` share the identical `ConnectionPool` object (`db.py:34-43`), `pool.connection()` hands out a fresh connection each call — sharing a pool is not sharing a transaction. So after the fix, there are still exactly two durability domains: the checkpoint (already committed by the time `_apply_result` starts) and the repo tables (now atomic with each other, but not with the checkpoint). A crash inside the new `_apply_result` transaction after `graph.invoke()` succeeded still leaves the checkpointed graph state (e.g. "interrupted, waiting on approval") out of sync with the repo tables (e.g. no `pending_actions` row, session still `running`) — the exact H2 symptom, just narrowed to a smaller window instead of eliminated.

**Why it happens:**
"Same pool" reads as "same transaction" to someone retrofitting transactions under time pressure, especially since `db.py`'s docstring already frames the checkpointer as built "on top of" the pool. The mental model of "one pool = one durability boundary" is wrong for `psycopg_pool`, and nothing in the code surfaces that distinction.

**How to avoid:**
Treat the checkpoint write and the repo write as two separate systems that must be reconciled, not as one that a bigger transaction closes. Options, cheapest first: (a) make `_apply_result`'s failure mode explicit and recoverable — on any exception, mark the session `failed` with a distinct reason ("state may be out of sync with checkpoint") rather than pretending the transaction covers everything; (b) add a startup/health reconciliation check that can detect a session whose checkpoint thread has state beyond what the repo reflects; (c) accept the residual window as a documented, deliberate trade (this is a portfolio project, not a bank) and write the ADR saying so explicitly rather than silently narrowing the window and calling it fixed.

**Warning signs:**
The H2 regression test only forces a failure *between* `repo.*` calls and never forces one *between* `graph.invoke()` returning and `_apply_result` starting — a green test suite here can hide the exact gap this pitfall describes.

**Phase to address:**
Fix-prompt Phase 2 (H2/H3). The ADR Phase 2 writes should explicitly scope what the transaction does and does not cover.

---

### Pitfall 2: `noUncheckedIndexedAccess` and mypy's `disallow_untyped_defs` are treated as a single on/off switch instead of two independently expensive dials

**What goes wrong:**
Both the backend (`H6`, mypy) and frontend (`H5`, TS `strict`) fixes are scoped as "turn strict mode on, fix what breaks." mypy's own guidance and multiple engineering write-ups converge on the same warning: `strict = True` bundles many independently expensive checks, and the single most expensive one when retrofitting onto existing code is **Any propagation from unannotated third-party calls** — one untyped call silently downgrades everything downstream of it to `Any`, which mypy then passes without complaint. A team that runs `mypy --strict`, sees a small error count, and declares victory can walk away with large silent gaps: functions that "type check" only because their inputs were already `Any`. This is a real risk here specifically because `app/tools/registry.py`'s three tools already structurally violate the `Tool` Protocol (H6) — fixing that mismatch by loosening the Protocol's `run` signature to `**kwargs: Any` (the easy way out) would make mypy stop complaining without making the "uniform tool-adapter interface" claim true, which is precisely the failure mode ADR-010/013's "verify, don't assume" standard exists to catch.

**Why it happens:**
Green CI is treated as proof of type safety, but a passing `mypy` run only proves the checks configured were satisfied — not that `Any` didn't quietly eat the interesting parts. Turning strict mode on for the first time on an existing codebase is exactly the scenario where this bites hardest, because there's no earlier baseline to diff against.

**How to avoid:**
When fixing H6, resolve `Tool.run`'s Protocol mismatch by making the Protocol match the actual keyword-specific signatures (or introduce a typed dispatch `Union`/`overload`) rather than widening it to `**kwargs: Any` — the fix-prompt's own instruction already says this ("make that claim true... do not silence it with `# type: ignore`"), but it's the path of least resistance under time pressure so it's worth flagging as the single most likely place this pitfall bites in this repo. Add `warn_return_any` and `disallow_any_generics` alongside the flags fix-prompt Phase 3 already lists, since those two are what catch "Any leaked back out of a function that looks typed." Verify the fix by intentionally reintroducing a keyword-mismatched `run` in one tool and confirming mypy rejects it (same ADR-007 standard the fix-prompt already applies elsewhere).

**Warning signs:**
Any new `# type: ignore` on the `Tool.run` line or on `registry.py`'s dispatch; a mypy run that reports fewer than the ~5 findings the day-4 review already identified without a corresponding code change that actually fixes rather than suppresses them.

**Phase to address:**
Fix-prompt Phase 3 (H5, H6, L19).

---

### Pitfall 3: The rate limiter and auth header are added to the backend and the frontend client update lands in a separate deploy, so the app breaks itself

**What goes wrong:**
This project has exactly one first-party client (the React frontend) and no external consumers, which simplifies most of the generic "don't break existing clients" playbook (versioning, deprecation windows, shadow-testing rate limits before enforcing) down to one real risk: the backend starts requiring an API key header or rejecting requests past a rate limit *before* the frontend is updated to send that header or handle a 429. Because `frontend/src/lib/api.ts` currently has no concept of an auth header at all, and the fix-prompt's Phase 5 and Phase 6 are different phases (auth is Phase 5, frontend polish is Phase 6), a literal reading of "do the phases in order, commit per phase" could produce a real Phase 5 commit where the deployed frontend can no longer reach the deployed backend — self-inflicted, not third-party, but exactly the failure mode "don't break existing clients" describes, on a system with a "clients" set of one.

**Why it happens:**
Phase boundaries in the fix-prompt are organized by *code layer* (backend security in Phase 5, frontend polish in Phase 6), not by *what has to ship together*. Auth is the one item that crosses that boundary and has to land atomically for the app to keep working end-to-end.

**How to avoid:**
Treat "wire the API key header into `frontend/src/lib/api.ts` and any fetch call sites" as part of the Phase 5 commit (or its own small immediately-following commit before Phase 6 starts), not deferred to Phase 6. Confirm end-to-end after Phase 5 by actually running the frontend against the backend with auth enabled — not just backend unit tests for "unauthenticated calls are rejected." Also decide up front whether the shared-secret key is exposed to the browser (a `VITE_*` env var, which is visible in the built bundle — acceptable only because this is a single-operator demo, not a multi-tenant product) and say so in the ADR the fix-prompt already asks for.

**Warning signs:**
A Phase 5 commit that adds the `429`/`401` behavior with backend tests only; the deployed Vercel frontend showing "Failed to fetch" / CORS or 401 errors against the deployed Render backend after a Phase 5 deploy but before Phase 6.

**Phase to address:**
Fix-prompt Phase 5 (H1) — pull the minimal frontend client change into this phase rather than Phase 6.

---

### Pitfall 4: The readiness fix adds a real `SELECT 1` but no timeout, turning a slow-but-alive database into a request pile-up instead of a fast, honest failure

**What goes wrong:**
H7's whole point is that `/health/ready` should "fail loudly" against a paused/unreachable Supabase project instead of reporting `ready` on config strings alone. The trap in implementing that fix is adding the DB round-trip without a short, explicit timeout on it. Community guidance on this exact pattern is consistent: a readiness check is supposed to be fast and cheap (`SELECT 1`, not a real query), and it needs its own timeout independent of the request's normal timeout, because the failure mode being guarded against — a paused Supabase project — is not "instant connection refused," it's "the connection attempt hangs while Supabase resumes" (the README already documents that a resumed project should not be queried until it reports `Active`). Without a timeout, `/health/ready` itself becomes the reliability risk the fix-prompt's own framing warns about: a monitoring tool or Render's own health-check hitting a hung readiness endpoint can pile up requests against the same limited pool (`max_size=5`), and every other endpoint slows down because the pool is exhausted servicing readiness checks that never return.

**Why it happens:**
The natural fix for "readiness lies" is "make it query the DB," and that's necessary but not sufficient — the specific way Supabase fails (slow resume, not instant refusal) is exactly the case a naive `SELECT 1` handles worst.

**How to avoid:**
Wrap the readiness `SELECT 1` in an explicit short timeout (a few hundred ms to low single-digit seconds, well under whatever Render/any external monitor's own timeout is), and treat a timeout the same as a query failure — downgrade to `not_ready`, don't hang. Do not use the main `pool.connection()` context manager without a statement/connect timeout for this specific call; consider a small dedicated timeout via `psycopg`'s `connect_timeout` or `pool.connection(timeout=...)`. Keep the config-string checks (already present) as separate fields alongside the new dependency check, per the fix-prompt's own instruction, so the frontend can distinguish "misconfigured" from "unreachable" from "slow."

**Warning signs:**
A load test or manual check where `/health/ready` takes longer than ~1s to respond in the happy path; Render's own health check (which the Phase 5 Dockerfile `HEALTHCHECK` and M9's fix add) flapping the service between healthy/unhealthy because the readiness check itself is the slow part.

**Phase to address:**
Fix-prompt Phase 5 (H7); verify explicitly during Day 6 deploy against a real paused-then-resuming Supabase project, not just a mocked DB failure.

---

### Pitfall 5: The Supabase-pause keep-alive mechanism is added but nothing monitors the keep-alive job itself

**What goes wrong:**
The project's own stated constraint (`PROJECT.md`: "Supabase free Postgres pauses after 7 days of inactivity — this is exactly what H7's readiness-check fix needs to detect") frames H7 as the mitigation, but a readiness check only *detects* a pause after the fact — it doesn't *prevent* one, and Render's own free-tier web service (per current Render/community guidance) spins down after inactivity too, so a Render instance that's asleep won't be pinging Supabase to keep it awake either, compounding the problem: two independent free-tier auto-sleep mechanisms (Render spin-down, Supabase pause) with no traffic to trigger either one to wake the other. The common failure mode reported in the wild for "keep-alive ping" fixes to this exact problem is that the keep-alive job (a GitHub Actions cron, an external scheduler) silently stops running — a workflow gets disabled, a free-tier scheduler quota is exhausted, a secret expires — and the pause happens anyway, except now there's a false sense of security because "we already fixed that."

**Why it happens:**
A keep-alive cron is an "install and forget" fix by nature, and the fix-prompt's scope (Days 5-7) doesn't include ongoing operational monitoring, so it's easy to treat "add a keep-alive workflow" as done rather than as an ongoing dependency that itself needs a health signal (e.g. GitHub Actions surfaces failed scheduled workflow runs via email/notifications, but only if someone is watching).

**How to avoid:**
Given the explicit "no paid infrastructure" constraint, the realistic options are: (a) accept the pause risk for a demo project and lean on H7's readiness check purely as *fast, honest detection* (the README should say "if this shows `not_ready`, the demo needs a manual wake-up visit first") rather than treating it as prevention; (b) add a lightweight scheduled GitHub Actions workflow that pings a real endpoint (not just a `curl` to a static page) on both Render and Supabase weekly, and treat a failed scheduled run as something to notice (GitHub's own UI flags failed scheduled workflows on the Actions tab). Given this is a portfolio demo meant to be reviewed on-demand rather than kept warm 24/7, (a) is the more honest choice — document that the demo may need ~30-60 seconds to wake on first visit after inactivity, matching Render free tier's own documented cold-start behavior, rather than fighting both platforms' free-tier sleep policies simultaneously.

**Warning signs:**
A demo link given to a reviewer that returns errors for the first request after a period of no traffic, with no loading/waking state in the frontend to explain why.

**Phase to address:**
Day 6 deploy; document the tradeoff explicitly in the README (Phase 7) rather than silently building a keep-alive mechanism whose own reliability isn't verified.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|------------------|
| Widening the `Tool` Protocol to `run(self, **kwargs: Any)` instead of fixing the mismatch | mypy passes immediately, zero tool code changes | Makes the Protocol decorative again — exactly H6's original complaint — and re-hides future signature drift | Never for this repo; the fix-prompt explicitly forbids it |
| Wrapping only `_apply_result`'s repo calls in a transaction and treating H2 as fully closed | Smaller, faster fix; passes the given regression test | Leaves the checkpointer/repo dual-write window open (Pitfall 1) | Acceptable only if documented as a known residual gap in the ADR, not if silently presented as "transactional now" |
| A shared-secret API key hardcoded as a `VITE_*` env var visible in the built frontend bundle | Fast to implement, no OAuth/session complexity | Not a real secret once shipped to a browser; fine only because there is exactly one operator and no other principal needs to be excluded | Acceptable for this single-operator portfolio demo; never acceptable if a second real user is ever added |
| Skipping the readiness-check timeout because "the DB is usually fast" | One less thing to configure | Turns a slow dependency into a request pile-up against the 5-connection pool (Pitfall 4) | Never — the whole reason for H7 is the exact scenario (Supabase resuming) where the DB is *not* fast |
| Treating the keep-alive cron as "prevention" rather than documenting the sleep/wake behavior | Feels like a complete fix | False confidence when the cron itself silently stops running (Pitfall 5) | Acceptable only paired with an explicit "demo may need to wake up" note in the README |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|-----------------|-------------------|
| Supabase (Postgres, free tier) | Assuming a paused project fails fast; not accounting for a resuming project answering slowly rather than refusing | Timeout every DB call from the readiness path explicitly; don't query immediately after a manual "resume," wait for `Active` status |
| psycopg_pool `ConnectionPool` | Assuming the pool always hands back a live connection; not setting `check=` or `max_lifetime` | `check=ConnectionPool.check_connection` plus `max_lifetime` shorter than Supabase's own idle/session timeout (M1 already scopes this — the specific values matter more than the `open=True` fix alone) |
| GitHub Actions on forked PRs | Assuming `secrets.*` are just empty strings that tests can skip past; in reality tests that assume a value is present will actively fail, not skip | Gate any secret-dependent test behind an explicit marker (`-m live`) that only runs where secrets are known to exist (main branch / manual dispatch), per H8's own plan; verify by running the suite with zero secrets, not by inspecting the workflow file |
| Render free web service | Assuming the container stays warm between requests / that background timers survive spin-down | Free-tier web services spin down after inactivity and cold-start on the next request; anything relying on an in-process scheduler (a keep-alive ping *from inside* the app) won't run while the service itself is asleep — the pinger has to live outside the service being kept alive |
| Vercel free static hosting | Assuming environment variables set in the Vercel dashboard are automatically in sync with `frontend/.env.example` | Treat `.env.example` as documentation only; verify the actual deployed `VITE_API_URL` / API key value in the Vercel project settings matches the live Render URL after every deploy, since L11 already flags default-value drift as a latent bug class in this repo |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Readiness check without a timeout against a resuming Supabase project | `/health/ready` and every other endpoint slow down together | Short explicit timeout on the readiness DB call, separate from normal request timeouts | The exact moment Supabase is paused-and-resuming, i.e. precisely when the check exists to help |
| `max_size=5` pool shared between readiness checks, normal API requests, and the LangGraph checkpointer | Under any concurrent load (even Render's own periodic health probe plus a real user), pool exhaustion causes request queuing | Keep the readiness path's DB usage minimal (`SELECT 1`, short timeout) so it can't monopolize the small pool; consider whether the checkpointer and API requests should share `max_size=5` at all on a single free-tier instance | Any concurrent access beyond a single interactive demo user — acceptable for this project's explicit single-instance scope, but worth a one-line ADR note since M1 already touches pool lifecycle |
| mypy strict mode run only in CI, never locally, on a codebase with real `Any` propagation | Long feedback loop; contributors push several commits before discovering a type error from an untyped third-party call two layers away | Run `mypy app` locally (pre-commit or a documented make target) before pushing, not just in CI | As soon as the backend gains a second contributor or a longer-lived branch |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Adding `slowapi` rate limiting keyed only on client IP behind Render's own reverse proxy without trusting `X-Forwarded-For` correctly | Every request appears to come from the same proxy IP, so the rate limit either never triggers (useless) or triggers for all users at once (false positive) | Verify Render's proxy sets `X-Forwarded-For` correctly and configure `slowapi`'s key function accordingly; test the 429 behavior against the actual deployed Render service, not just localhost |
| Leaving `allow_credentials=True` on CORS after adding a shared-secret header auth scheme (H1 already flags this pairing as worth reviewing) | `allow_credentials=True` with a wildcard-adjacent origin config is a classic CORS misconfiguration; combined with a bearer-style header auth (not cookies), credentials mode buys nothing and only adds risk surface | Set `allow_credentials=False` once the auth scheme is header-based rather than cookie-based, and lock `allow_origins` to the exact Vercel deployment URL rather than `*` |
| Using a `pull_request_target`-style workflow to let fork PR CI reach the shared Supabase DB "just for this one job" | Even though the current `ci.yml` correctly uses plain `pull_request` (safe: no secrets, read-only token for forks), any future change to `pull_request_target` to work around H8's fork-secrets problem would flip this: base-repo secrets become available to arbitrary fork code unless `actions/checkout` is deliberately pinned to the base ref | Solve H8 with a Postgres service container + migration step (already the fix-prompt's plan) instead of reaching for `pull_request_target`; if `pull_request_target` is ever considered, require first-time-contributor approval and never check out the fork's head with it |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-------------------|
| Escape key on the approval modal doing nothing, or silently dismissing without a decision recorded | A reviewer/demo-user presses Escape expecting to close, either gets stuck or accidentally reads as "no interaction happened" while the session is actually still `awaiting_approval` | Fix-prompt Phase 6 already flags deciding-and-documenting Escape's behavior as a real hazard ("dismissing an approval prompt by accident is a real hazard") — the safest default for an irreversible-action gate is Escape = no-op (does not approve or reject), not Escape = Reject, since an accidental Escape should never silently take the destructive path either |
| A cold-started Render backend (Pitfall 5) with no loading state on the frontend during the ~30-60s free-tier wake-up | First-time visitor to the demo sees blank screens / failed fetches and assumes the app is broken | Add a "waking up" state to the frontend's initial load / `BackendStatus` component distinct from a genuine `not_ready` failure, so a slow-but-working cold start reads differently than a broken deploy |
| Focus trap implemented by hand instead of native `<dialog>`, with the focusable-element list computed once at mount | If the modal's content changes after mount (e.g. an error message appears, per M5/L4's `error` prop), newly-rendered focusable elements (like a retry button) may fall outside the trap | Recompute the focusable-element list on each Tab keydown rather than caching it, or use native `<dialog>` + `showModal()` (the fix-prompt already lists this as the first option) which handles this automatically |

## "Looks Done But Isn't" Checklist

- [ ] **H2's transaction fix:** Often verified only by forcing a failure *between* `repo.*` calls — verify it also documents (or closes) the separate window between `graph.invoke()`'s checkpoint commit and `_apply_result`'s transaction start (Pitfall 1).
- [ ] **H6's mypy pass:** Often verified by a shrinking error count alone — verify no new `# type: ignore` or `**kwargs: Any` widening was used to get there; specifically check `registry.py`'s `Tool.run` signature is honest, not loosened.
- [ ] **H1's auth rollout:** Often verified by backend tests asserting 401/429 alone — verify the deployed frontend (`frontend/src/lib/api.ts` and every fetch call site) actually sends the required header end-to-end against a locally running backend with auth enabled, before the Day 6 deploy.
- [ ] **H7's readiness fix:** Often verified against a reachable DB returning success/failure — verify it also has an explicit timeout, and manually verify behavior against a real paused-then-resuming Supabase project (per fix-prompt's own "verify, don't assume" standard already used for C1/C2/C3/C4).
- [ ] **H8's fork-CI fix:** Often verified by reading the workflow YAML — verify by actually confirming a run with zero secrets set passes, per the fix-prompt's own final-verification step 4.
- [ ] **M11's accessible modal:** Often verified with a screen-reader smoke test alone — verify Escape's behavior is deliberate and tested (not accidentally wired to Reject), and that focus return-to-trigger works when the modal closes via Approve, Reject, *and* whatever Escape does.
- [ ] **Day 6 deploy:** Often "done" when the first request after deploy succeeds — verify a *second* demo visit after a multi-day gap (or a manually-forced Supabase pause) still works, since that's the actual failure mode H7/Pitfall 4/Pitfall 5 exist to catch.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|-----------------|------------------|
| Checkpointer/repo dual-write window left open after H2 (Pitfall 1) | LOW | Document as a known, accepted residual gap in the H2 ADR; add a manual reconciliation note (query for sessions whose checkpoint thread implies more progress than their repo row) rather than re-architecting persistence |
| `Tool` Protocol quietly widened to `**kwargs: Any` to pass mypy (Pitfall 2) | LOW | Revert the widening, fix the actual signature mismatch per the fix-prompt's original instruction; this is a same-day fix once caught |
| Frontend/backend auth deploy skew (Pitfall 3) | LOW | Render/Vercel free tiers redeploy in minutes; ship the missing frontend header change as an immediate follow-up commit, no rollback needed since both are still free-tier and stateless to redeploy |
| Readiness check hangs under load (Pitfall 4) | MEDIUM | Add the missing timeout, redeploy; if the pool was exhausted, a Render service restart clears it — but diagnosing "why did everything slow down" without the fix already in place costs real debugging time |
| Keep-alive job silently stopped and Supabase paused (Pitfall 5) | LOW | Manually resume the project via Supabase Studio, wait for `Active` status before querying (per the researched restore guidance — data is retained up to 1 year even after pause), then re-verify the keep-alive workflow is actually enabled |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|----------------|
| Checkpointer/repo dual-write window (Pitfall 1) | Fix-prompt Phase 2 (H2/H3) | Regression test forces failure both *within* `_apply_result` and *between* `graph.invoke()` returning and `_apply_result` starting; ADR states which window is closed vs. accepted |
| `Any`-explosion / Protocol-widening trap (Pitfall 2) | Fix-prompt Phase 3 (H6) | mypy run with `disallow_any_generics` + `warn_return_any` added on top of the fix-prompt's listed flags; reintroduce a keyword-mismatched `run` and confirm mypy rejects it by name |
| Auth/frontend deploy skew (Pitfall 3) | Fix-prompt Phase 5 (H1), frontend client change pulled into this phase rather than Phase 6 | Manual end-to-end run: frontend dev server against backend with auth enabled, before Day 6 deploy |
| Readiness check without timeout (Pitfall 4) | Fix-prompt Phase 5 (H7) | Manual verification against a real paused/resuming Supabase project, per the fix-prompt's own "verify by hand" standard already applied to C1/C2 |
| Keep-alive mechanism with no monitoring of itself (Pitfall 5) | Day 6 deploy + Phase 7 documentation | README states the actual cold-start/pause behavior a reviewer should expect, rather than silently relying on an unmonitored cron |
| Accessible modal Escape/focus edge cases (M11's own scope) | Fix-prompt Phase 6 | RTL tests per the fix-prompt's own list (focus moves in, Tab cycles within, Escape behavior is deliberate and tested) |
| Fork PR secrets (H8's own scope) | Fix-prompt Phase 5 | Full suite run with zero secrets set, per the fix-prompt's own final-verification step 4 |

## Sources

- [Project Pausing — Supabase Docs](https://supabase.com/docs/guides/platform/free-project-pausing) — official, HIGH confidence
- [How to Prevent Your Supabase Project Database from Being Paused Using GitHub Actions — DEV Community](https://dev.to/jps27cse/how-to-prevent-your-supabase-project-database-from-being-paused-using-github-actions-3hel) — community, cross-checked against official docs, MEDIUM
- [Connection pools — psycopg 3 documentation](https://www.psycopg.org/psycopg3/docs/advanced/pool.html) — official, HIGH confidence
- [`psycopg_pool` release notes](https://www.psycopg.org/psycopg3/docs/news_pool.html) — official, HIGH confidence
- [Add on-connect callback to check connections — psycopg/psycopg#656](https://github.com/psycopg/psycopg/issues/656) — official project issue tracker, HIGH confidence
- [Securely using `pull_request_target` — GitHub Docs](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target) — official, HIGH confidence
- [`pull_request` vs. `pull_request_target` — Paul Serban](https://paulserban.eu/blog/post/pullrequest-vs-pullrequesttarget-the-github-actions-trigger-hiding-a-security-nightmare/) — community, cross-checked against official docs, MEDIUM
- [Using mypy with an existing codebase — mypy documentation](https://mypy.readthedocs.io/en/stable/existing_code.html) — official, HIGH confidence
- [From zero to type-safe: static type checking a large-scale Python codebase — Eightfold](https://eightfold.ai/engineering-blog/static-type-checking-large-scale-python-codebase/) — practitioner report, MEDIUM confidence
- [Common Accessibility Issues with Modals — OpenReplay](https://blog.openreplay.com/common-accessibility-issues-modals-fix/) — community, cross-checked against MDN/W3C `inert`/dialog guidance, MEDIUM
- [Accessible modal dialogs using `inert` — Lars Magnus](https://larsmagnus.co/blog/accessible-modal-dialogs-using-inert) — community, MEDIUM
- [API Rate Limit Rollout Checklist — Moments Log](https://www.momentslog.com/development/api-rate-limit-rollout-checklist-protect-capacity-without-breaking-legitimate-clients) — community, MEDIUM
- [Understanding the Dual-Write Problem and Its Solutions — Confluent](https://www.confluent.io/blog/dual-write-problem/) — vendor engineering blog, cross-checked against general distributed-systems consensus, MEDIUM
- Direct repo grounding (not web sources): `D:\agent-ops\backend\app\session_runner.py`, `D:\agent-ops\backend\app\repository.py`, `D:\agent-ops\backend\app\db.py`, `D:\agent-ops\frontend\src\components\ApprovalModal.tsx`, `D:\agent-ops\.github\workflows\ci.yml`, `D:\agent-ops\reviews\day-4-review.md`, `D:\agent-ops\reviews\day-4-fix-prompt.md`, `D:\agent-ops\.planning\PROJECT.md` — HIGH confidence (primary source, this codebase)

---
*Pitfalls research for: AI agent orchestration copilot (LangGraph + FastAPI + Postgres + React) — Days 5-7 hardening/security/deploy retrofit*
*Researched: 2026-08-25*
