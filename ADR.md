# Architecture Decision Records

Format: one numbered record per decision. Each records the context, the choice,
and — per project rules — what was explicitly given up by choosing it. Records
are append-only; if a decision is later reversed, add a new record that
supersedes it rather than editing history.

---

## ADR-001: Agent graph framework — LangGraph over CrewAI

**Date:** 2026-08-22 (Day 1)

**Context**

The project's hard requirements are: every irreversible action pauses for a
real approval state machine (not a UI illusion), every session has a full
trace of agent decisions and tool calls, and tool failures must be caught,
logged, and retried/re-planned rather than silently swallowed. Two frameworks
were evaluated: LangGraph and CrewAI (web search conducted 2026-08-22 across
nine current sources including ZenML, DataCamp, TrueFoundry, IBM Developer,
and dev.to comparison pieces published this year).

Findings from that search:

- **LangGraph** models the agent system as an explicit stateful directed
  graph. It ships built-in persistence/checkpointing, streaming, conditional
  branching, and fan-out/fan-in parallel execution. Multiple 2026 sources
  describe it as the choice "for enterprises building mission-critical
  systems" specifically because of its state management, retries, and
  human-in-the-loop checkpoints — LangGraph 0.4 (April 2026) explicitly
  sharpened HITL checkpoint support.
- **CrewAI** models the system as a crew of role-based agents and optimizes
  for speed of prototyping. Sources are consistent that it has *no built-in
  checkpointing for long-running workflows*, *limited control over
  agent-to-agent communication*, and *coarse-grained error handling*.
  Multiple sources independently note that "teams that start with CrewAI for
  prototyping often migrate to LangGraph when they need production-grade
  state management and conditional routing."

**Decision**

Use LangGraph for the planner → delegate → tool-call → observe → decide-next
graph.

The deciding factor is not raw capability but the shape of the hard
requirements: a real pending → approved/rejected → executed state machine and
a full decision trace are naturally modeled as graph state and node
transitions in LangGraph, and would have to be hand-built on top of CrewAI's
coarser abstraction anyway — at which point CrewAI's main advantage
(faster-to-write happy path) is spent paying down the gap.

**What we gave up**

- CrewAI's faster initial time-to-prototype for simple sequential/hierarchical
  agent crews — not relevant here since Day 2 needs branching/retry logic from
  the start, not a later migration.
- CrewAI's role-based framing (`Agent(role=, goal=, backstory=)`), which reads
  more naturally for a "team of specialists" mental model than LangGraph's
  graph-of-nodes framing. This is a documentation/onboarding cost, not a
  functional one — the trace viewer (Day 4) will need to do more work to make
  LangGraph's graph state legible to a non-engineer reviewer than CrewAI's
  narrative would have for free.
- A larger ecosystem of pre-built "crew" templates for common patterns
  (researcher+writer+reviewer, etc.) that CrewAI ships with.

**Confirms/amends 2.2:** confirms the stack default as given.

---

## ADR-002: LLM provider — Gemini primary, OpenRouter automatic fallback, one interface

**Date:** 2026-08-22 (Day 1)

**Context**

Section 2.2 mandates Gemini as primary with OpenRouter as an automatic
fallback behind one provider-agnostic interface, and mandates picking the
OpenRouter free model live rather than from a stale list. Two things needed
live verification before committing to defaults: (1) which Gemini model ID is
actually current, since free-tier model lineups have been rotating
aggressively; (2) which `:free` OpenRouter model currently supports tool
calling.

**(1) Gemini model.** Fetched `ai.google.dev/gemini-api/docs/models` directly
(not a blog aggregator — several ranked search results for "Gemini free tier
2026" were low-quality SEO content that disagreed with each other on basic
facts, so official docs were used as ground truth). Confirmed:
`gemini-2.0-flash` — the value that shipped in the original `.env.example`
template — was **shut down** (deprecated Feb 2026, retired March 3, 2026).
Current stable Flash-tier models as of 2026-08-22: `gemini-3.7-flash` (newest,
most capable, released Aug 13 2026), `gemini-3.6-flash`, `gemini-3.5-flash`,
`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`. Google's rate-limits page
does not publish exact free-tier RPD/RPM numbers on the doc page itself
(directs to AI Studio's live per-key dashboard instead), so the pick optimizes
for "current and documented as cost-effective/high-throughput" rather than a
specific quota number that can't be verified from outside a real account.

**Decision:** default `GEMINI_MODEL=gemini-3.1-flash-lite` — current (not on
the deprecated list), explicitly documented by Google as "frontier-class
performance rivaling larger models at a fraction of the cost," i.e. the
lite/cost-effective tier most likely to carry a generous free quota. This
replaces the stale `gemini-2.0-flash` default in `.env.example`.

**(2) OpenRouter model.** Hardcoding a model name from training data was
explicitly disallowed by the project brief — the free-model lineup rotates.
Queried `https://openrouter.ai/api/v1/models` live (not summarized by an
intermediary model — fetched raw JSON via `curl` and filtered with a small
script to avoid a summarizing model inventing plausible-sounding names).
Snapshot taken 2026-08-22: 422 total models, 17 are `:free` **and** advertise
`tools`/`tool_choice` in `supported_parameters`. Candidates considered:
`google/gemma-4-31b-it:free` (262K ctx, well-known lineage, no
`structured_outputs`), `z-ai/glm-5.2:free` (256K ctx, full param set),
`nvidia/nemotron-3-super-120b-a12b:free` (262K ctx, MoE with only ~12B active
params so inference stays fast despite the 120B label, full parameter set
including `structured_outputs` — useful for forcing well-formed tool-call
JSON, which matters more for a fallback path that only fires under failure
conditions and therefore gets far less real-world exercise than the primary).

**Decision:** default `OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free`,
selected for the fullest tool-calling parameter support of the free+tool-
calling candidates at time of writing.

**Both together:** one `LLMProvider` interface (`backend/app/llm/`) with a
`GeminiProvider` and `OpenRouterProvider` implementation. A thin
`FailoverProvider` wraps both: calls Gemini first, catches timeout/5xx/
rate-limit errors specifically (not blanket `except Exception`, so a genuine
bug in our own code doesn't get silently masked as a "provider failure" and
routed to the fallback), logs the failover event to the trace log as its own
decision node, and retries once on OpenRouter before surfacing an error to the
planner. This is real resilience infrastructure, not a shim — it is the
thing this project can point to in an interview as "here is a provider
outage I designed around," and Day 2's tests assert the failover path
directly (mocked Gemini failure → OpenRouter call observed) rather than
relying on a real outage to exercise it.

**What we gave up**

- A single-provider integration would be simpler to reason about and debug
  (one set of quirks, one SDK, one error taxonomy instead of two). Two
  providers means two sets of tool-calling JSON-schema quirks to normalize
  behind the shared interface.
- Free-tier OpenRouter model selection is a moving target — the specific
  model pinned today (`nvidia/nemotron-3-super-120b-a12b:free`) may be
  withdrawn or replaced before Day 6's deploy. Mitigated by keeping it in
  `.env` (change without a code change) and documenting the live re-check
  command in README rather than trusting this ADR's snapshot indefinitely.
- Both free tiers are rate-limited (OpenRouter: 20 req/min, 50 req/day per
  model with no card on file; Gemini: exact free RPD not published, verify in
  AI Studio). Day 5's per-session tool-call caps exist partly to keep the
  project inside these limits, which constrains how ambitious a single demo
  session's task graph can be.

**Confirms/amends 2.2:** confirms the dual-provider architecture; amends the
specific default model IDs (the `.env.example` template's Gemini default was
stale/deprecated; the OpenRouter default was intentionally left blank in the
template and is now filled from a live snapshot).

---

## ADR-003: Free-tier terms verified 2026-08-22 (not trusted from memory)

**Date:** 2026-08-22 (Day 1)

**Context**

Per the hard constraint to verify free-tier terms with a live search rather
than build against possibly-stale numbers, each platform's current terms were
checked.

**Findings:**

| Platform | Verified term | Design implication |
|---|---|---|
| Supabase | Free projects pause after **7 days of total inactivity** (no DB activity — dashboard visits/cached API hits don't count); resume takes ~30s; 2 free projects max; 500MB DB storage, 1GB file storage, 5GB bandwidth, no card required. | README gets an explicit "wake the project" note (Day 5), since this repo won't be touched daily post-build. |
| Render | Free web services **spin down after 15 minutes of inactivity** (this changed from a previous 30-minute window); cold start is 30-60s; 512MB RAM / 0.1 CPU; 750 free compute hours/month; 100GB bandwidth. | README gets a "first request will be slow" note (2.2 already anticipated this; confirmed the exact window is now 15 min, tighter than commonly assumed). |
| Vercel | Hobby plan is free indefinitely, no card required, **but is restricted to personal/non-commercial use** by ToS — a portfolio project with no billing/monetization is fine. 100GB bandwidth, 1M function invocations, 4 CPU-hours compute/month. | No design change; noted so a reviewer doesn't mistake this for a commercial deployment. |
| OpenRouter | `:free` models: 20 requests/min, **50 requests/day** per model with $0 balance (no card). Buying $10 of credit (one-time, non-expiring) raises the daily cap to 1000 but was ruled out to stay strictly free-tier-only per the hard constraint. | Confirms 2.2's plan to reserve OpenRouter calls for the fallback path's own test coverage, not routine dev-loop iteration — 50/day would starve real iteration otherwise. |
| Gemini API | Free tier exists per-key via AI Studio; exact published RPD/RPM aren't listed on the public rate-limits doc page (varies by "usage tier," viewable only inside a live AI Studio account) — see ADR-002. | Dev-loop iteration budget is unknown until a real key is provisioned; code should treat Gemini 429s as a normal, expected, handled case (see ADR-002 failover), not an edge case. |
| GitHub Actions | Free for public repositories (unlimited minutes on standard runners). | Repo should stay public for the free CI minutes to apply without a card on file; this is also required for Render/Vercel's free GitHub-connected auto-deploy to see the repo without extra permissions. |

**Decision:** proceed exactly per 2.2's stack with no paid upgrades; add the
two README notes called out above.

**What we gave up:** nothing changed from the original plan — this ADR exists
to record that the numbers were independently verified today (2026-08-22)
rather than assumed, per the hard constraint, and to pin the exact current
figures (7-day Supabase pause, 15-minute Render spin-down, 50/day OpenRouter
cap) since several of these are tighter or different from commonly-repeated
older figures.

---

## ADR-004: Dependency versions pinned from live registries, not memory

**Date:** 2026-08-22 (Day 1)

**Context**

Training-data knowledge of package versions is stale by definition by
2026-08-22. Rather than guess current major versions (risking a scaffold that
can't actually `pip install`/`npm install` against what's published today),
current stable versions were queried directly from PyPI's and npm's JSON APIs.

**Findings (snapshot 2026-08-22):** `langgraph` 1.2.11, `fastapi` 0.141.1,
`pydantic` 2.13.4, `uvicorn` 0.52.4, `ruff` 0.16.4, `pytest` 9.1.1, `supabase`
2.31.0, `httpx` 0.28.1, `openai` 3.3.1 (used as the OpenRouter client — it
exposes an OpenAI-compatible chat-completions API), `langchain-openai` 1.6.0,
`langchain-google-genai` 4.3.5, `tenacity` 9.1.4, `structlog` 26.1.0,
`slowapi` 0.1.10, `python-dotenv` 1.2.3; `react` 19.2.8, `vite` 8.2.2,
`typescript` 7.0.2, `tailwindcss` 4.3.3, `@vitejs/plugin-react` 6.1.0,
`vitest` 4.1.11, `eslint` 10.9.0.

**Decision:** pin these as the scaffold's initial dependency versions.

**What we gave up:** none of these have been run against yet — Day 2+ may
surface a real incompatibility (e.g. a major-version breaking change) that
forces a downgrade of one package. If that happens it gets its own ADR entry
rather than a silent version edit.

---

## ADR-005: OpenRouter client uses the OpenAI-compatible SDK, not a bespoke HTTP client

**Date:** 2026-08-22 (Day 1)

**Context:** OpenRouter exposes an OpenAI-compatible `/chat/completions` API.
LangChain ships `langchain-openai`, which can point at any OpenAI-compatible
base URL (`base_url=https://openrouter.ai/api/v1`).

**Decision:** implement `OpenRouterProvider` on top of `langchain-openai`'s
`ChatOpenAI` class with a custom `base_url`, rather than hand-rolling HTTP
calls or pulling in a separate OpenRouter-specific SDK.

**What we gave up:** OpenRouter-specific features exposed outside the OpenAI-
compatible surface (e.g. its provider-routing preferences API, its native
`/models` metadata beyond what a chat client needs) aren't reachable through
this client. If Day 2 needs those, add a thin `httpx` call for that one
endpoint rather than replacing the whole client — the live `/models` query
used for ADR-002 above was already done this way (raw `httpx`/`curl`, not the
SDK), and that pattern is reusable in the app's build/startup path if a
runtime re-check is added later.

---

## ADR-006: `Settings.env_file` anchored to repo root by path, not by CWD

**Date:** 2026-08-22 (post-Day 1 fix)

**Context**

`backend/app/config.py` originally set `SettingsConfigDict(env_file=".env")`.
pydantic-settings resolves a relative `env_file` against the process's
current working directory at `Settings()` construction time — it does not
search parent directories the way, say, `git` or a `.editorconfig` resolver
would. README's own documented local-dev flow is `cd backend` followed by
`cp ../.env.example ../.env` (creating `.env` at the repo root) and then
`uvicorn app.main:app --reload` (CWD = `backend/`). Under that flow the
relative `".env"` resolved to `backend/.env`, which never existed, so the
app silently read nothing.

This was invisible rather than a crash: every `Settings` field defaults to
`""`, so a fully-unconfigured `Settings()` is valid and constructs without
error. `/health/ready` — the endpoint whose entire job (per ADR/Day 1 design)
is to make exactly this kind of misconfiguration loud — reported
`not_ready` with every check `false`, which reads identically to "you
haven't filled in `.env` yet" and to "the app can't find the `.env` you did
fill in." A developer following the README exactly as written would hit
this every time.

**Decision:** compute the env file path once at module import time, anchored
to `config.py`'s own file location rather than the caller's CWD:

```python
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"
```

and pass `env_file=_ENV_FILE` (an absolute `Path`, not a string) into
`SettingsConfigDict`. This makes `.env` discovery independent of whatever
directory a process happens to be started from — `uvicorn` from `backend/`,
`pytest` from `backend/`, or a hypothetical future entrypoint from the repo
root all resolve to the same file.

Verified:
- `parents[2]` from `backend/app/config.py` is genuinely the repo root —
  computed directly (`python -c "print(Path(...).resolve().parents[2])"`)
  rather than assumed, since an off-by-one here silently reintroduces the
  same bug one directory over.
- The documented README flow now works end-to-end: booted `uvicorn` from
  `backend/` against a fully-populated root `.env` and confirmed
  `/health/ready` returns `{"status": "ready", ...}` with all four checks
  `true` (previously all `false`).
- The deployment shape (no `.env` file anywhere, config from the platform's
  real environment variables — Render/Vercel) still works: booted the app
  with `.env` temporarily moved aside and config passed as real env vars;
  no error, `/health/ready` still reports `ready`. An `env_file` pointing at
  a path that doesn't exist is a no-op in pydantic-settings, not an error.
- Test-suite determinism is unaffected: `Settings(_env_file=None)` (used
  throughout `tests/` and in `conftest.py`'s `make_client`) still means
  "ignore any `.env` entirely," confirmed against a machine with a fully
  populated real root `.env` — and explicit keyword overrides still take
  precedence over both the dotenv source and defaults.

**What we gave up**

- `config.py` now has an opinion about the repo's directory shape
  (`backend/app/` sitting exactly two levels under the repo root) baked in
  as a magic index (`parents[2]`). If `config.py` ever moves to a different
  depth, this silently points at the wrong file again — the same failure
  mode this ADR fixes, one refactor later. Mitigated only by the new
  regression test asserting the resolved path's shape (`tests/test_config.py`
  independently recomputes the expected root from its own file location
  rather than importing config.py's arithmetic, so the two can't drift
  together undetected) — there is no compile-time guarantee, only a test
  that must be kept passing.
- A more conventional fix would be an explicit `ENV_FILE` environment
  variable or a CLI flag, letting the deployer/developer state the path
  rather than the code inferring it from its own location. That would be
  more explicit but adds a setup step this project's free-tier/solo-dev
  context doesn't need — Render and Vercel never use a `.env` file at all
  (real platform env vars), and the only place this mattered was local dev,
  where "just works regardless of which directory you're in" is worth more
  than explicitness.
