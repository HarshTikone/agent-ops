# Agent Ops — Master Build Prompt for Claude Code

Paste everything below this line as your **first message** to Claude Code, inside a fresh, empty
git repo folder. Read the whole file once before you start — the prerequisites section has to be
done by *you* first; the rest is what Claude Code executes.

---

## 0. One correction before you start

Grok's **API** is not free — only the chat playground is. Billed usage starts at real API calls
(roughly $2/$6 per million input/output tokens as of this writing, and pricing moves, so don't
trust that number by the time you read this). Since "everything free" is a hard constraint, the
prompt below wires the agents to **Google Gemini** instead — it has a genuine free tier through
Google AI Studio, no card required, and it's the same API your existing RAG project already uses,
so nothing new to learn. If you'd rather use Grok for the parts you build by hand later, that's
fine — just don't let the autonomous 7-day build depend on a paid key.

---

## 1. Do this before opening Claude Code (~20 minutes, all free, no card except where noted)

**Accounts**
- [ ] GitHub account + a new **empty, private** repo (e.g. `agent-ops`) — don't add a README, .gitignore, or license from GitHub's UI, Claude Code will create those
- [ ] Google AI Studio → generate a **Gemini API key** (free tier, no card) — aistudio.google.com/apikey — this is the **primary** model
- [ ] OpenRouter account → generate an **OpenRouter API key** (openrouter.ai/keys, no card needed) — this is the **backup** model. Free (`:free`-suffixed) models on OpenRouter are capped at 20 requests/min and 50/day per model with no card on file (rises to 1,000/day if you ever add $10 in credit, entirely optional). That ceiling is too low to be the primary model during heavy Day 2–3 dev loops, which is exactly why it's wired in as a fallback, not the default
- [ ] Supabase account → new free project (Postgres + pgvector + auth, no card) — note the project
      URL (Settings -> API Keys) and the **secret key** (`sb_secret_...`, on the "API Keys" tab,
      not "Legacy API Keys" — this is the current replacement for the old service_role key)
- [ ] Render account → connect your GitHub (free web service tier, no card)
- [ ] Vercel account → connect your GitHub (free Hobby tier, no card)

**Local machine**
- [ ] Node.js LTS + npm (or pnpm)
- [ ] Python 3.11+ and `uv` (or pip)
- [ ] Docker Desktop — used for local testing before every deploy, not just at the end
- [ ] Git, and the **GitHub CLI** (`gh`) — run `gh auth login` once. This is what lets Claude Code create commits, push, open PRs, and manage the repo end-to-end without you touching a browser
- [ ] Claude Code installed and signed in, run once inside the empty repo folder so it's initialized

**No plugins or paid marketplace items are required.** Claude Code's built-in Bash, file, and web
tools cover everything here. Two small setup steps that materially help this specific build:
- If your Claude Code supports **custom subagents**, this prompt asks it to create one at
  `.claude/agents/reviewer.md` on Day 1 — that's what runs the self-review gate before every
  deploy. It creates this itself; you don't need to pre-install anything.
- If a **GitHub MCP server** is available in your setup, it's a nice-to-have for richer PR/issue
  handling, but the `gh` CLI alone is entirely sufficient for everything this plan asks for — don't
  block Day 1 on installing it.

**Put your keys in `.env` locally, never in a message to Claude Code and never in a commit.**
```
GEMINI_API_KEY=
OPENROUTER_API_KEY=
SUPABASE_URL=
SUPABASE_SECRET_KEY=
DATABASE_URL=
```

---

## 2. The prompt — paste from here down

You are the sole engineer building **Agent Ops** — a multi-agent orchestration copilot — over the
next 7 days, working inside this repo. Read this entire prompt before writing anything. This is a
portfolio project meant to demonstrate production-grade agentic-AI engineering, not a tutorial or
a notebook demo — a past reviewer called an earlier project "incomplete" for reading like an
explainer instead of a solved problem, and that is the bar every day here has to clear.

### 2.1 What you're building

A system where a **planner agent** breaks an incoming task into steps and delegates each to
tool-using sub-agents (start with: web search, a notes/document store, and a calculator or
code-execution tool). Every irreversible action pauses for **human approval** before it runs.
Every session has **persistent memory** and a **full trace** of what each agent decided, which
tool it called, and why — visible in the UI, not just in logs.

### 2.2 Stack (default to this; you may swap a piece only if you write down why in `ADR.md`)

- Backend: Python, FastAPI, LangGraph for the agent graph
- LLM: Gemini (via `GEMINI_API_KEY`) as the **primary** provider, with **OpenRouter**
  (`OPENROUTER_API_KEY`) wired in as an **automatic fallback** — both sit behind one
  provider-agnostic interface, so a Gemini error, timeout, or rate-limit triggers a transparent
  retry on an OpenRouter free model rather than failing the run. This doubles as a legitimate
  resilience feature to point to in an interview, not just a workaround. Query OpenRouter's live
  `/models` endpoint at build time to pick a current free (`:free`) model that supports tool/
  function calling — the free-model lineup changes often, so don't hardcode a model name from
  anything written before today. Because the OpenRouter free tier caps out at 50 requests/day with
  no card on file, use Gemini for all of Day 2–5's dev-loop testing and reserve OpenRouter calls
  for the actual fallback path and its own test coverage, not routine iteration.
- Frontend: React + TypeScript + Vite + Tailwind
- Database / memory / trace log: Supabase Postgres, pgvector extension enabled for any embedding
  storage the agents need
- Backend deploy: Render (free web service, connected to this GitHub repo, auto-deploy on `main`)
- Frontend deploy: Vercel (free Hobby, connected to this GitHub repo, auto-deploy on `main`)
- CI: GitHub Actions — lint + test + build on every push, required to pass before merge to `main`

Before you write a single line of application code, **verify current free-tier terms yourself**
with a web search — pricing pages change, and you should not build against numbers I gave you
without checking. Two known friction points to design around from the start: Supabase free
projects pause after a week of total inactivity (fine for active build days; add a note in
`README.md` about waking it if this gets checked long after the build week), and Render's free
web services cold-start after idling (acceptable for a portfolio project; mention it in the README
so a reviewer isn't confused by a slow first request).

### 2.3 Hard constraints — do not violate these

1. **Free-tier only.** If a step would require a paid plan or a credit card that risks a charge,
   stop and flag it instead of proceeding.
2. **Real commits, not padding.** Aim for roughly 10 commits per day, but every commit must be a
   real, atomic, working unit of change with a Conventional Commits message
   (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `ci:`). Never split one change into hollow commits
   just to hit a number, and never let the count fall to 1–2 "big bang" commits either — if a
   day's work naturally atomizes into 7 or 13, that's fine, 10 is a target, not a rule.
3. **Stay inside today's scope.** Section 3 below breaks the 7 days into daily scopes. Do not start
   tomorrow's work early even if today finishes fast — instead use the extra time to close out
   today's "past just a demo" checklist items more thoroughly (see 2.5).
4. **No deploy without a review pass.** Before any deploy to Render/Vercel (not just the final
   one — every time `main` changes in a way that will trigger a deploy), run the self-review gate
   in 2.4 first.
5. **Never commit secrets.** `.env` is gitignored from commit #1. Before every push, confirm no key
   or token is in the diff.

### 2.4 The self-review gate (run before every deploy, not only on Day 7)

Create a subagent at `.claude/agents/reviewer.md` — its job is to review a diff the way a skeptical
staff engineer would, independent from the reasoning that produced the code. Before any deploy:

1. Run the reviewer subagent against the full diff since the last deploy.
2. It writes findings to `REVIEW.md` — real defects and gaps only, ranked by severity, each with a
   concrete failure scenario (what input/state causes what wrong behavior).
3. Fix every finding that's a real correctness, security, or missing-error-handling issue before
   deploying. Note explicitly in `REVIEW.md` any finding you deliberately didn't fix and why.
4. Only then deploy, smoke-test the live URL, and commit the result.

### 2.5 "Past just a demo" — the checklist every day's work has to clear

- At least one shown failure mode per feature area (a tool call that fails, an agent that picks the
  wrong path, a malformed input) — and what the system does about it, not just the happy path
- At least one measured number by the end of the week (latency, a tool-selection accuracy rate,
  cost per session) — not just "it works"
- One real design decision written down in `ADR.md` with what you gave up by choosing it
- Real tests on the core logic (`/tests`), not just manual clicking
- Enough realistic data/scenarios that edge cases show up on their own, not five toy examples

### 2.6 Daily check-in format

At the end of each day, before stopping, output:
- What shipped today (bullet list, matched against that day's scope in Section 3)
- Commit count for the day and the range (`git log --oneline` since yesterday's tag)
- Anything in `REVIEW.md` still open and why
- A one-line git tag for the day, e.g. `git tag day-1-complete`
- What's planned for tomorrow, unchanged from Section 3 unless something in today's work forces a
  real re-plan — if so, explain the change before proceeding

---

## 3. The 7 days

**Day 1 — Research, decisions, scaffold.** Web search current best practice for LangGraph vs.
CrewAI and settle the choice; write `ARCHITECTURE.md` and `ADR.md` explaining the stack decisions
from 2.2 (confirm or amend them); scaffold `backend/` (FastAPI) and `frontend/` (Vite+React+TS+
Tailwind); Dockerfiles for both; `.env.example`; GitHub Actions CI skeleton (lint+test, even if
tests are empty placeholders); pre-commit hooks (ruff/black, eslint/prettier); `README.md`
skeleton; issue/PR templates and `LICENSE`. Nothing here calls the LLM yet — that starts Day 2.

**Day 2 — Core agent engine.** Planner graph in LangGraph: decompose → delegate → tool-call →
observe → decide-next. Three tools: web search, a notes/document store, a calculator or
code-exec tool. The Gemini adapter and the OpenRouter fallback adapter behind the same
provider-agnostic interface, with the automatic failover between them. Unit tests on the
planner's tool-selection logic and on the failover itself (mock a Gemini failure, assert it
lands on OpenRouter), including at least one case where the planner should retry or re-plan
after a failure. Every tool failure is caught and logged, never silently swallowed.

**Day 3 — Memory, approval, tracing.** Supabase schema for session memory and the trace log.
Human-in-the-loop approval as a real state machine (pending → approved/rejected → executed), not
a UI-only illusion. Trace logger capturing every agent decision and tool call. API endpoints:
create session, send message, approve/reject a pending action, fetch a session's trace.
Integration test that runs a full session including a forced tool failure and the retry.

**Day 4 — Frontend.** Chat UI, a trace viewer panel (this is the differentiator — make it show
the reasoning, not just the final answer), the approval modal, a session list. Supabase Auth
if there's time (nice polish, not required for functionality). Loading and error states for
every API call, not just the success path. Component tests with Vitest/RTL.

**Day 5 — Hardening and docs.** Expand tests to explicitly cover the failure modes named in 2.5.
Add rate limiting and per-session timeouts/max-tool-call caps so a runaway agent can't burn the
free-tier quota. Structured logging and a basic metrics endpoint. Write the real `README.md`:
lead with the problem being solved and how, not installation steps — those go below the fold.

**Day 6 — Dockerize and deploy.** Finalize Dockerfiles, add `docker-compose.yml` for local dev.
Connect Render and Vercel to the repo for auto-deploy on `main`; branch protection requiring CI
to pass before merge. Run the review gate (2.4), then do the first real deploy, then smoke-test
the live URLs and fix whatever only shows up in production.

**Day 7 — Review, polish, ship.** Full review-gate pass across the whole repo, not just the
latest diff — treat it like an external code review. Fix every real finding. Record a 60–90
second demo (screen recording of a full session: task in, plan, tool calls, an approval prompt,
the trace view), embed it at the top of the README. Add a build-status badge. Final secrets audit.
Tag `v1.0.0`, deploy that tag, and write `RETROSPECTIVE.md` — what the hardest bug was, what
you'd do differently, and the two-sentence version of this project for a resume bullet and a
LinkedIn post.

---

Begin with Day 1. Do not touch Day 2 scope today.
