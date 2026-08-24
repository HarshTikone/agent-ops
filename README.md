# Agent Ops

[![CI](https://github.com/HarshTikone/agent-ops/actions/workflows/ci.yml/badge.svg)](https://github.com/HarshTikone/agent-ops/actions/workflows/ci.yml)

> **Status: Day 1 of a 7-day build.** This README is a working skeleton —
> it gets rewritten Day 5 to lead with the problem and the demo, not
> installation steps. Until then, treat this as internal setup docs.

A multi-agent orchestration copilot: a planner agent breaks an incoming task
into steps and delegates each to a tool-using sub-agent (web search, a
notes/document store, a calculator). Every irreversible action pauses for
human approval before it runs. Every session has persistent memory and a
full trace of what each agent decided, which tool it called, and why —
visible in the UI, not just in logs.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how it's built and
[`ADR.md`](ADR.md) for why each stack/design choice was made (including the
LangGraph-vs-CrewAI decision and the Gemini+OpenRouter failover design).

## Stack

- **Backend:** Python, FastAPI, LangGraph
- **LLM:** Gemini (primary) with an automatic OpenRouter `:free`-model
  fallback behind one provider interface
- **Frontend:** React, TypeScript, Vite, Tailwind
- **Database:** Supabase Postgres + pgvector
- **Deploy:** Render (backend), Vercel (frontend), both auto-deploy on `main`
- **CI:** GitHub Actions (lint + test + build on every push)

## Local development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
cp ../.env.example ../.env      # fill in real values, see below
python scripts/migrate.py       # applies backend/migrations/*.sql — run once, and again after any schema change
uvicorn app.main:app --reload
```

Check it's up: `curl http://localhost:8000/health` and
`curl http://localhost:8000/health/ready` (the second reports which of
Gemini/OpenRouter/Supabase/DB config is missing, without ever printing a
secret value).

Sessions, messages, the trace log, and the approval state machine (Day 3)
live in Postgres — `POST /sessions`, `POST /sessions/{id}/messages`,
`GET /sessions/{id}/trace`, `POST /approvals/{id}/approve` /
`.../reject`. See `/docs` for the full schema, or `ADR.md` (ADR-014/015/016)
for how the approval pause survives across separate requests.

Run checks locally exactly as CI does:

```bash
ruff check .
black --check .
pytest -v
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_URL — defaults to http://localhost:8000
npm run dev
```

```bash
npm run lint
npm run format:check
npm test
npm run build
```

### Both, via Docker

`docker-compose.yml` (added Day 6) will bring up both services together for
local dev parity with the deploy topology. Until then, each service's own
`Dockerfile` builds and runs standalone — see each directory.

### Pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

Runs the same ruff/black/eslint/prettier checks CI runs, before you commit.

## Environment variables

Copy `.env.example` to `.env` at the repo root (backend reads it) and
`frontend/.env.example` to `frontend/.env` (Vite only reads env files from
within `frontend/`). Every variable is documented inline in the `.example`
files, including which free-tier signup page to get each key from and how to
pick a current OpenRouter `:free` tool-calling model (the lineup rotates —
see `ADR-002` in `ADR.md` for the live-verification method).

**Never commit `.env`.** It's gitignored from the first commit in this repo;
double-check `git status` before pushing if you ever see it listed.

## Free-tier quirks you'll hit

- **Supabase** free projects pause after 7 days of *total* inactivity (no DB
  queries — dashboard visits don't count). If you're reading this long after
  the build week, open the Supabase dashboard once to wake the project
  before hitting the API — resume takes about 30 seconds.
- **Render** free web services spin down after 15 minutes idle. The first
  request after a while will take 30-60 seconds to cold-start — that's
  expected, not a bug, if you're smoke-testing the live URL.
- **OpenRouter** free models cap at 20 requests/minute and 50/day per model
  with no card on file — reserved for the fallback path and its own tests,
  not routine dev-loop iteration (use Gemini for that).

## Repo layout

```
backend/            FastAPI app, agent graph, tests
backend/migrations/ SQL schema, applied by backend/scripts/migrate.py
frontend/           React + Vite + Tailwind app, tests
.github/            CI workflow, issue/PR templates
ADR.md              Architecture Decision Records — what we chose and gave up
ARCHITECTURE.md     System design: components, data flow, deployment topology
```

## Build log

This project is being built in public over 7 days as a portfolio piece. Each
day is tagged (`day-1-complete`, `day-2-complete`, ...) once its scope from
the build plan is done. `RETROSPECTIVE.md` (Day 7) has the full writeup.
