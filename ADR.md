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

  **Correction (see ADR-007): the claim in the paragraph above that this risk
  is "mitigated ... by the new regression test" does not hold as originally
  written — the original test asserted the `_ENV_FILE` constant, never the
  wiring. ADR-007 records what actually catches the mutation.**

---

## ADR-007: The regression tests from ADR-006 didn't regress-test anything — caught by mutation testing

**Date:** 2026-08-22 (post-ADR-006 correction)

**Context**

ADR-006 added four tests alongside the `.env`-loading fix and claimed, in its
own "what we gave up" section, that the `parents[2]` magic-index risk was
"mitigated ... by the new regression test asserting the resolved path's
shape." That claim was checked with a mutation test — reintroduce the exact
original bug (`env_file=_ENV_FILE` back to `env_file=".env"`) while leaving
the new `_REPO_ROOT`/`_ENV_FILE` constants untouched and correct — and it did
not hold.

**What actually happened, verified directly (not assumed):**

With the mutation applied, `pytest -v` reported **13 passed, 0 failed** — all
four "regression" tests green — while a direct manual check
(`Settings().gemini_api_key` from `backend/` against the real, fully
populated root `.env`) returned `''`. The exact bug ADR-006 fixed was fully
back, and nothing in the suite noticed.

**Why each test missed it, examined individually:**

- `test_env_file_is_absolute_and_anchored_to_repo_root` asserted on the
  `_ENV_FILE` *constant* — `_ENV_FILE.is_absolute()` and
  `_REPO_ROOT / ".env" == _ENV_FILE`. It never read
  `Settings.model_config["env_file"]`, so a mutation that makes
  `model_config` ignore the (still-correct) constant is invisible to it by
  construction. Keeping a computed value correct and *wiring it in* are two
  separate facts; this test only ever checked the first.
- `test_settings_loads_real_env_file_regardless_of_cwd` (renamed
  `test_settings_loads_an_explicit_env_file_path_regardless_of_cwd` below)
  passed `_env_file=fake_env` as an explicit constructor override. Per
  pydantic-settings' precedence rules, an explicit init-time `_env_file`
  always overrides `model_config`'s `env_file`, regardless of what the
  latter is set to — so this test exercises pydantic-settings' own dotenv-
  loading mechanism, never `config.py`'s wiring. It passed identically
  against the original bug and against the reintroduced mutation. Its
  docstring claimed it "confirms Settings still finds the module-anchored
  file," which was false — it never touched the module-anchored file at
  all. The docstring was corrected in place of the assertions, which were
  fine for what they actually test (kept, renamed, re-scoped honestly).
- `test_env_file_none_ignores_real_dotenv_even_when_present` and
  `test_env_file_pointing_at_nonexistent_path_is_a_no_op` both also pass
  explicit `_env_file` overrides (`None` and a nonexistent path,
  respectively) for the same structural reason — correct and worth keeping
  for what they do cover (test-suite determinism; the no-`.env`-at-all
  deployment shape), but neither was ever regression coverage for this bug,
  and ADR-006 didn't claim otherwise for these two specifically.

**The generalizable lesson:** a test written immediately after fixing a bug,
which passes against the fixed code, is not evidence it would fail against
the bug — those are different claims, and only a mutation test (deliberately
reintroduce the exact bug, confirm the test now fails, then revert) checks
the second one. "The suite is green" was insufficient evidence here; it was
green against both the correct code and the reintroduced bug.

**Decision:** add two tests that were verified, by the same reintroduce-the-
mutation-and-confirm-red process, to actually catch it:

1. `test_model_config_actually_uses_the_anchored_path` — reads
   `Settings.model_config["env_file"]` directly (not the `_ENV_FILE`
   constant) and asserts it equals `_ENV_FILE`. Cheap, deterministic, and
   fails immediately on the wiring mutation.
2. `test_settings_reads_repo_root_env_when_started_from_backend` — copies
   the real `app/` package (located via `Path(app_package.__file__)`, never
   a hardcoded relative path) into a throwaway `<tmp>/repo/backend/app`,
   writes a fake `.env` at `<tmp>/repo/.env`, and runs
   `from app.config import Settings; print(Settings().gemini_api_key)` in a
   fresh subprocess with CWD set to the fake `backend/` — mirroring
   production's exact directory shape and exactly how the README says to
   start `uvicorn`, without ever touching the developer's real `.env`.

Both were confirmed, by direct reproduction, to: **fail** (naming both
tests) when `env_file=_ENV_FILE` is reverted to `env_file=".env"`, and
**pass** once reverted back — the same verification standard ADR-006 should
have applied to its original four before claiming mitigation.

**What we gave up**

- The subprocess-based end-to-end test is slower and more complex than a
  pure in-process assertion (it shells out to a fresh Python interpreter and
  does a filesystem copy per run). This is deliberate: the wiring assertion
  alone (`test_model_config_actually_uses_the_anchored_path`) would catch
  the specific mutation tested above, but a subtly different bug — e.g.
  `model_config` pointing at a *different* wrong-but-absolute path — could
  satisfy a wiring assertion that only checks "is it `_ENV_FILE`" without
  ever proving `_ENV_FILE` resolves to a location that actually works from
  the documented startup directory. The subprocess test proves the real,
  observable behavior end-to-end at the cost of runtime.
- This ADR does not re-run mutation testing across the rest of the test
  suite (`test_health.py`, the frontend tests) — the same failure mode
  (assert-the-helper-not-the-behavior) could exist elsewhere and hasn't
  been checked. Flagged here rather than silently assumed fine.

---

## ADR-008: Correction — ADR-004's `typescript` version was never actually installed

**Date:** 2026-08-22 (post-scaffold correction)

**Context**

ADR-004 lists `typescript` 7.0.2 among the versions "pinned as the scaffold's
initial dependency versions" from a live npm registry query. Checked directly
against what's actually in the repo:

- `frontend/package.json`: `"typescript": "~6.0.2"`.
- `frontend/package-lock.json`: resolves `node_modules/typescript` to
  **6.0.3** (an in-range patch bump `~6.0.2` allows).
- Peer-dependency ceiling, read directly from `package-lock.json`:
  `@typescript-eslint/eslint-plugin`, `@typescript-eslint/parser`,
  `@typescript-eslint/*`, and `typescript-eslint` itself all declare
  `peerDependencies.typescript: ">=4.8.4 <6.1.0"`. TypeScript 7.0.2 is
  outside that range by a full major version — it could never have
  installed alongside `typescript-eslint` 8.67.0 (also pinned per ADR-004),
  regardless of what the registry's `latest` tag said at query time.

**What actually happened:** `create-vite`'s `react-ts` template scaffolds its
own `package.json` with a TypeScript range chosen for compatibility with the
rest of its generated toolchain — it does not defer to whatever an
independent "what's current on npm" query says. ADR-004's version table was
compiled from live registry lookups made *before* running `npm create
vite@latest`, and the TypeScript entry was never reconciled against what the
scaffolding tool actually wrote. Every other package in ADR-004's list was
spot-checked the same way — reading the resolved version directly out of
`package-lock.json` (backend equivalently out of `requirements.txt`/
`requirements-dev.txt`, which are hand-written rather than tool-generated) —
and **all of them match ADR-004 exactly**: `react` 19.2.8, `vite` 8.2.2,
`tailwindcss` 4.3.3, `@vitejs/plugin-react` 6.1.0, `vitest` 4.1.11, `eslint`
10.9.0 on the frontend; `langgraph` 1.2.11, `fastapi` 0.141.1, `pydantic`
2.13.4, `uvicorn` 0.52.4, `ruff` 0.16.4, `pytest` 9.1.1, `supabase` 2.31.0,
`httpx` 0.28.1, `openai` 3.3.1, `langchain-openai` 1.6.0,
`langchain-google-genai` 4.3.5, `tenacity` 9.1.4, `structlog` 26.1.0,
`slowapi` 0.1.10, `python-dotenv` 1.2.3 on the backend. `typescript` is the
only drift found.

**Decision:** correct the record, not the code. `typescript` `~6.0.2`
(resolving `6.0.3`) is the right pin — it's what's actually installed,
actually builds, and actually satisfies `typescript-eslint`'s peer range.
ADR-004's text is left as originally written (append-only convention); this
entry is the correction of record. No file changes result from this ADR.

**What we gave up**

- Nothing functionally — no code or dependency changes here, only a
  documentation correction. The cost paid was earlier: ADR-004 stated a
  fact (a specific version number) without verifying it against the
  artifact it was supposedly describing (`package.json`/`package-lock.json`),
  checking only the external registry instead. The lesson generalizes past
  this one field: a "verified against a live source" claim needs the
  live source to be *the thing the ADR is actually about*, not a step
  earlier in the pipeline that a later tool (here, `create-vite`'s own
  dependency resolution) can silently override.

---

## ADR-009: `/health/ready` distinguishes "can't serve" from "no failover safety net"

**Date:** 2026-08-22 (post-scaffold correction)

**Context**

`/health/ready` originally computed `ready = all(checks.values())` across
all four config checks (Gemini key, OpenRouter key, Supabase, database) —
treating a missing OpenRouter key exactly like a missing Gemini key or a
missing database connection: any one absent reported the whole deploy
`not_ready`. Meanwhile `Settings.llm_providers_configured` (Gemini-only)
existed on the model but was never read by the endpoint.

Per ADR-002, OpenRouter is a fallback that fires *only* on a Gemini
timeout/5xx/rate-limit — and deliberately not on other failure shapes: the
`FailoverProvider` catches those specific exceptions so "a genuine bug in
our own code doesn't get silently masked as a 'provider failure.'" A missing
or invalid `GEMINI_API_KEY` produces an auth/config error, not a
timeout/5xx/rate-limit — so it is, by ADR-002's own design, *not* a
condition the failover catches. Concretely:

- **Gemini + Supabase + database configured, OpenRouter absent:** the system
  can serve every request end-to-end today. It has no safety net if Gemini
  has an outage mid-session, but that's a risk, not a current outage.
- **OpenRouter configured, Gemini absent:** the system can serve *nothing*
  — the failover path that would reach OpenRouter never triggers for a
  missing primary key, only for specific primary-call failures.

Treating these identically as "not_ready" conflates "cannot serve a single
request right now" with "can serve, but is one Gemini outage away from
having no fallback" — two very different situations a deploy operator needs
to tell apart at a glance.

**Decision:** three-way `status`, computed from `llm_providers_configured`
(now wired into the endpoint) plus the Supabase/database checks as the
hard "can this instance do anything at all" gate, with OpenRouter absence
downgrading `ready` to `degraded` rather than to `not_ready`:

```python
can_serve = settings.llm_providers_configured and supabase_configured and database_configured
status = "not_ready" if not can_serve else ("degraded" if not openrouter_api_key_set else "ready")
```

- `not_ready`: missing Gemini, Supabase, or the database — cannot serve any
  request.
- `degraded`: can serve every request; no OpenRouter fallback configured.
- `ready`: fully configured.

The `checks` object in the response is unchanged — all four booleans are
still reported individually, so a deploy operator can still see exactly
which piece is missing regardless of which bucket `status` falls into.

Verified live (not just via the test suite) by starting the real server
under three constructed environments with the developer's real root `.env`
moved aside: Gemini+Supabase+DB set, OpenRouter unset →
`{"status":"degraded", ...}`; OpenRouter+Supabase+DB set, Gemini unset →
`{"status":"not_ready", ...}`; and, with the real `.env` restored, the
actual fully-configured deploy → `{"status":"ready", ...}`. All three match
the decision table above exactly.

Frontend (`BackendStatus.tsx`) updated to match: `ReadinessResponse.status`
is now `'ready' | 'degraded' | 'not_ready'`, and the status text renders in
one of three colors (green / amber / red) via a `Record`-typed lookup keyed
on the union type itself — so an exhaustiveness check comes for free: adding
a fourth status value to the type without adding it to `statusColor` is a
TypeScript error, not a silent fallback to some default color. Previously
`degraded` and `not_ready` would both have rendered identically in amber,
which is exactly the "can't tell these apart at a glance" problem this ADR
exists to fix — a reviewer glancing at a demo deploy showing amber could not
tell "still fully functional" from "broken" without reading the text.

**What we gave up**

- A simpler binary `ready`/`not_ready` is one less state for every future
  consumer of this endpoint to handle — Day 5's metrics endpoint and any
  future uptime-monitor integration now need to decide what to do with
  `degraded` (probably: page on `not_ready`, just log `degraded`), which is
  a real design question this ADR is deferring rather than answering.
- The hard/soft split is a judgment call about ADR-002's failover behavior
  holding as currently designed. If Day 2's actual implementation ends up
  catching a broader class of Gemini failures than "timeout/5xx/rate-limit"
  (e.g. treating a 401 as failover-eligible too, to be more lenient), the
  premise here — "a missing Gemini key can never be rescued by OpenRouter"
  — would need re-checking, and this ADR would need a follow-up.
  `test_readiness_not_ready_when_only_openrouter_key_present` documents the
  current assumption in a way that a future Day 2 change would need to
  consciously revisit, but nothing enforces that revisit happening.
- `llm_providers_configured`'s definition ("Gemini configured" only, per its
  existing docstring) now doubles as this endpoint's serving gate. It was
  already documented as intended for exactly this ("Used by the health
  endpoint... to fail a session creation early") — this ADR is what
  actually wires that intent in, closing the gap where it was defined but
  never called.

---

## ADR-010: LLM provider client implementation — LangChain chat models, with a verified per-provider exception-translation boundary

**Date:** 2026-08-23 (Day 2)

**Context**

ADR-002 committed to one `LLMProvider` interface with `GeminiProvider` and
`OpenRouterProvider` behind it, and a `FailoverProvider` that catches
"timeout/5xx/rate-limit ... not blanket `except Exception`." ADR-002 didn't
specify how each provider's exceptions get translated into that narrow set —
that had to be verified against the actual pinned packages
(`langchain-google-genai` 4.3.5, `langchain-openai` 1.6.0, ADR-004), not
assumed from either package's older APIs or from training data.

**What was verified, directly, before writing any translation code:**

Both packages are built on `langchain_core.exceptions`' unified `ModelError`
hierarchy (`ModelTimeoutError`, `ModelRateLimitError`, `ModelAPIError`,
`ModelConnectionError`, `ModelAuthenticationError`, `ModelPermissionDeniedError`,
`ModelInvalidRequestError`, `ModelNotFoundError`, `ContextOverflowError`) —
read directly out of each package's source
(`langchain_openai/chat_models/base.py`, `langchain_google_genai/chat_models.py`),
not inferred. But the two packages don't map to it identically:

- **OpenRouter** (`langchain-openai`'s `ChatOpenAI`, pointed at OpenRouter's
  base URL per ADR-005): multiple-inherits its exception classes from both
  the OpenAI SDK's own type *and* the matching `ModelError` type — e.g.
  `class OpenAITimeoutError(openai.APITimeoutError, ModelTimeoutError)`. All
  four transient shapes (timeout, rate-limit, 5xx, connection failure) are
  normalized this way.
- **Gemini** (`langchain-google-genai`'s `ChatGoogleGenerativeAI`): only
  normalizes rate-limit (`GoogleRateLimitError` → `ModelRateLimitError`) and
  5xx (`GoogleAPIError` → `ModelAPIError`) — confirmed by reading
  `_CLIENT_ERROR_TYPES` and `_handle_server_error` directly. A genuine
  network timeout or connection failure is **not** wrapped; it surfaces as a
  raw `httpx.TimeoutException` / `httpx.ConnectError`, because those errors
  happen below the layer that does the status-code-based translation.

**Decision:** each provider implements its own `except` clauses, tailored to
what its underlying package actually raises, rather than sharing one generic
translation function:

- `GeminiProvider` catches `ModelRateLimitError` → `ProviderRateLimitError`,
  `ModelAPIError` → `ProviderServerError`, and
  `(httpx.TimeoutException, httpx.ConnectError)` → `ProviderTimeoutError`.
- `OpenRouterProvider` catches `ModelRateLimitError` → `ProviderRateLimitError`,
  `ModelAPIError` → `ProviderServerError`, and
  `(ModelTimeoutError, ModelConnectionError)` → `ProviderTimeoutError`.
- Both `max_retries=0` on the underlying client — the SDK's own internal
  retry loop (6 attempts by default for Gemini) would otherwise hide a
  transient failure from `FailoverProvider` for all of them before ever
  raising, making the failover far slower than the failure actually needed
  and undermining the retry-count assumptions ADR-012's bounds are built on.
- Everything else (`ModelAuthenticationError`, `ModelPermissionDeniedError`,
  `ModelInvalidRequestError`, `ModelNotFoundError`, or any exception outside
  this list) is not caught by either provider and propagates unchanged — the
  ADR-002/ADR-009 guarantee that a missing/invalid key can never look
  failover-eligible. Verified directly:
  `test_gemini_provider_does_not_translate_auth_errors` and
  `test_openrouter_provider_does_not_translate_auth_errors`
  (`tests/test_llm_providers.py`) construct a `ModelAuthenticationError` and
  assert it comes back out unchanged, not wrapped or swallowed.

`ChatOpenAI`/`ChatGoogleGenerativeAI`'s own `.bind_tools()` and normalized
`.tool_calls` are used as-is (not hand-rolled) — this is what absorbs
Gemini's and OpenAI's different native function-calling JSON schemas behind
one interface, which ADR-002's "what we gave up" section flagged as real
work; LangChain had already done it at the pinned versions.

**What we gave up**

- Two different `except` clauses per provider, instead of one shared
  translation function, is more code to keep in sync if a future
  `langchain-google-genai` release starts normalizing timeouts too (at which
  point `GeminiProvider`'s httpx-catching branch becomes dead code, not
  wrong code — a version bump could silently make it superfluous without
  any test failing to say so).
- Both providers' `except` blocks are only as narrow as this ADR's
  verification against *these exact pinned versions* — a version bump to
  either package needs the same read-the-source verification repeated, not
  assumed to still hold. `tests/test_llm_providers.py` pins behavior, not
  the underlying package version; nothing fails loudly on a version bump
  that quietly changes which exception a given failure raises.

---

## ADR-011: Day 2 tool choices — Tavily for web search, an AST calculator over code-exec

**Date:** 2026-08-23 (Day 2)

**Context**

ARCHITECTURE.md §2 names the three Day 2 tools without picking concrete
implementations: web search (must be free-tier, no card), and calculator-
or-code-exec for the third. Both needed a live-verified choice, not a
memory-based one, per this project's established method (ADR-002).

**Web search: Tavily**

Queried live (`WebSearch`, then cross-checked against Tavily's own docs
directly, not the aggregator SEO content mixed into the search results —
several results, e.g. from generic "best free API" roundup sites, weren't
trustworthy as a primary source on their own, per the same standard ADR-002
applied to Gemini-vs-blog-aggregator content). Confirmed straight from
`docs.tavily.com`: 1,000 free credits/month, no card, 1 credit per basic
search, 100 requests/min on a free "Development" key. Auth is a bearer
header (`Authorization: Bearer tvly-...`) — verified directly, since the
older convention (an `api_key` body field, which is what a first draft of
`WebSearchTool` used) is not how the current API actually authenticates and
would have failed on the very first live call.

Added to the free-tier table (extending ADR-003's, not editing it):

| Platform | Verified term | Design implication |
|---|---|---|
| Tavily | Free "Development" key: 1,000 credits/month, 100 req/min, no card; 1 credit per basic search. | 1,000/month is generous relative to OpenRouter's 50/day — no special "reserve for tests only" discipline needed for web search the way ADR-003 requires for OpenRouter, though the test suite still mocks it (see "what we gave up" below). |

Verified live end-to-end (not just via the mocked test suite): a real
`POST https://api.tavily.com/search` call against the actual account key
returned real, on-topic results matching the exact response shape
`WebSearchTool` parses (`results[].title/url/content`).

**Calculator over code-exec**

Chose the calculator, not a code-execution tool, for the third slot.
Code-exec is more impressive to point at in an interview, but it means
running LLM-generated code — that needs a real sandbox (a subprocess with
resource/network limits, or a per-call container) to be safe to expose on a
public Render URL where anyone can submit a task. Building and verifying
that sandbox properly is a multi-day concern on its own, not a Day 2 slot;
doing it badly (e.g. `exec()` in-process with a naive blocklist) would be
worse than not having the feature, since a blocklist is trivially bypassable
and this app has no auth gate in front of it yet (that's Day 3+).

Implemented `CalculatorTool` as an AST walker over `ast.parse(expr,
mode="eval")`, allowing only numeric literals, the arithmetic operators, and
a four-function allow-list (`abs`, `round`, `min`, `max`) — not `eval()`.
`tests/test_tools_calculator.py::test_disallowed_expression_elements_are_rejected`
is parametrized directly with injection-shaped inputs
(`__import__('os').system(...)`, `open('/etc/passwd').read()`,
`[].__class__.__base__.__subclasses__()`) specifically so the test fails
loudly if a future "simplification" swaps the AST walker back for `eval()`.

**What we gave up**

- Tavily's free tier is generous enough that `test_tools_web_search.py`
  could arguably have made a small number of real calls in CI without
  meaningfully touching the 1,000/month budget — mocked anyway, for
  consistency with the OpenRouter discipline (ADR-003) and so CI behavior
  never depends on Tavily's uptime or the account's remaining credits.
- No code-exec tool this project. If Day 5+ hardening adds real per-session
  sandboxing infrastructure for other reasons, revisiting this with its own
  ADR is reasonable — but that's a deliberate future decision, not an
  oversight here.
- The calculator's function allow-list (`abs`/`round`/`min`/`max`) is
  arbitrary and small. Extending it means auditing each new function for
  whether it can be abused to leak information or misbehave on adversarial
  input (e.g. `round()` with a huge second argument) — not a rubber stamp.

---

## ADR-012: `decide_next` — retry vs. re-plan vs. give-up, and the bounds on each

**Date:** 2026-08-23 (Day 2)

**Context**

ARCHITECTURE.md §2/§4 says `decide_next` "decides whether to proceed... 
re-plan..., retry..., or request human approval" but doesn't specify how it
tells "retry" apart from "re-plan," or what stops either from looping
forever. The brief calls this out directly as the project's single most
interview-relevant piece of logic and explicitly warns against it becoming
"an implicit if-chain nobody can explain."

**Decision: the tool adapter, not the graph, classifies its own failure.**

`ToolError(message, *, transient: bool)` is the only exception a tool
adapter is allowed to raise (mirroring `LLMProvider`'s narrow
`TransientProviderError` split, ADR-002/ADR-010, applied to tools). The
adapter that raised it is in the best position to know which shape its own
failure is: a `web_search` network timeout is obviously transient; a
`calculator` `SyntaxError` on a malformed expression is obviously not —
retrying the *exact same* bad expression will fail identically every time,
so retrying it is wasted budget. `decide_next_node` never inspects an
exception itself; it only reads the `transient` flag `tool_call_node`
already recorded in state.

**Decision: three independent bounds, checked in this priority order**
(`app/graph/limits.py`):

1. `MAX_TOOL_CALLS = 10` — a hard ceiling across the *whole run*, checked
   first, regardless of the other two counters. The backstop against a
   pathological loop, not the primary control.
2. `MAX_STEP_RETRIES = 2` — a transiently-failing step gets up to 2 extra
   attempts (3 total) before its failure is treated as un-retryable.
3. `MAX_REPLANS = 1` — the whole run gets one trip back to the planner
   before a further failure means giving up outright.

**Decision: the actual routing table**, given the current step's outcome:

- Step succeeded, more steps remain → advance to the next step (`delegate`).
- Step succeeded, plan exhausted → `finalize` (synthesize the answer).
- Step failed, `transient=True` and under the retry budget → retry the
  *same* step (`delegate` again, same plan index).
- Step failed, `transient=False`, OR transient but retry budget spent, AND
  the re-plan budget isn't spent → re-plan: go back to `planner` with a new
  `HumanMessage` describing what failed and why, so the LLM sees the
  failure as real conversation context, not a silent retry.
- Step failed and the re-plan budget is also spent → give up: `status =
  "failed"`, a `final_answer` stating what couldn't be completed. Never a
  crash, never a silently truncated run.
- An unknown tool name in the plan (the planner selected something not in
  the registry) is treated as a `transient=False` step failure through the
  exact same path — a wrong tool-selection decision re-plans, it doesn't
  crash the graph. `tests/test_graph_decide_next.py::test_unknown_tool_selection_is_treated_as_a_permanent_failure_and_replans`
  covers this directly.

Verified against the compiled graph (not just the routing function in
isolation) in `tests/test_graph_decide_next.py`: a pure-retry run (fails
once, transient, then succeeds — planner called exactly once), a
pure-re-plan run (fails once, permanent, re-plans onto a different tool —
re-plan's `HumanMessage` context asserted present in the actual LLM call the
re-plan makes), a full escalation run (retries exhaust, re-plan happens,
the *new* step also keeps failing, re-plan budget is spent → give up — with
an explicit assertion that this gives up on the re-plan budget and not the
hard cap, since both could plausibly trigger), and the hard-cap run
in isolation (an 11-step all-succeeding plan stops at exactly 10 tool
calls). See ADR-013 for the live run against real Gemini exercising the
retry and re-plan paths end to end, and the two real bugs that live run
caught which none of these mocked/scripted tests did.

**What we gave up**

- `MAX_STEP_RETRIES = 2` and `MAX_REPLANS = 1` are judgment calls, not
  measured numbers — there's no production traffic yet to tune them against.
  A more sophisticated policy (e.g. exponential backoff between retries, or
  scaling the re-plan budget with plan length) is deferred; these are the
  simplest bounds that satisfy "an agent loop with no cap can burn a day's
  quota" without adding complexity Day 2 doesn't need yet.
- A step that fails permanently on its very first attempt still "wastes" one
  full re-plan's LLM call before giving up, even though retrying was never
  going to help — the alternative (skip straight to give-up on certain
  failure types) would need a *second* classification dimension beyond
  transient/permanent ("is this worth re-planning around at all"), which is
  more machinery than Day 2's three-tool, single-session scope justifies.
- Day 3's real approval state machine and Day 5's rate limiting are separate
  concerns from these bounds — `MAX_TOOL_CALLS` protects a single run's
  quota spend, not the account-wide OpenRouter/Gemini budget across
  concurrent sessions, which Day 5 owns.

---

## ADR-013: Live-verification findings — two real bugs no mocked test caught, plus mutation-test evidence

**Date:** 2026-08-23 (Day 2)

**Context**

Per this project's Day 2 instructions and ADR-007's standing lesson ("a test
that passes after a fix is not evidence it would fail against the bug it
claims to prevent"), every mocked test in this day's suite was
mutation-tested, and the graph was run end to end against the real Gemini
API — including a forced tool failure — before being called done. The live
runs surfaced two real bugs that 85 passing mocked/scripted tests had not
caught, because none of them happened to construct the exact message shapes
a real Gemini call produces.

**Bug 1 — `AIMessage.content` is not always a `str`.**

`llm_response_from_ai_message` originally did
`content = ai_message.content if isinstance(ai_message.content, str) else str(ai_message.content)`.
A live call against `gemini-3.1-flash-lite` returned `.content` as a list of
content blocks (`[{"type": "text", "text": "47 times 89 is 4,183.", "extras":
{"signature": "..."}}]`), not a plain string — so the `else` branch fired
and `final_answer` came back as a stringified Python list
(`"[{'type': 'text', 'text': '47 times 89 is 4,183.', 'extras': {...}}]"`)
instead of the answer. No exception was raised; `status` was still `"done"`.
Every existing test constructed `AIMessage(content="plain string")` by hand,
so none exercised this shape. Fixed by using `AIMessage.text` (a `str`
subclass LangChain provides specifically to normalize both the plain-string
and content-block shapes) instead of hand-checking `.content`'s type.
`tests/test_llm_base.py::test_extracts_plain_text_from_gemini_style_content_blocks`
reproduces the exact real shape and was mutation-verified: reverting to the
original `isinstance`/`str()` line turns it red with the exact malformed
output the live run produced, confirming this test would have caught the
original bug had it existed before the live run found it. Reverted back to
the `.text`-based fix, confirmed green (85 passed).

**Bug 2 — retrying a step appended a second `ToolMessage` for the same `tool_call_id`.**

The first live failure-path run (calculator fails transiently once, retries,
succeeds) produced a *correct* trace and `status: "done"` but an **empty**
`final_answer`, with no error logged anywhere. `observe_node` appended a
`ToolMessage` on every observation, including the failed attempt — so a
retried step left two `ToolMessage`s in history both claiming to answer the
same `tool_call_id` from the single `AIMessage` that requested it once. This
is an invalid tool-calling message sequence; the Gemini API accepted it
(`200 OK`) but answered `finalize`'s synthesis call with empty content
instead of erroring, so nothing in the code raised or logged a failure.
Reproduced directly (not just inferred) by hand-constructing that exact
message sequence and calling `GeminiProvider.generate` on it. Fixed by
having `observe_node` drop any existing `ToolMessage` for the current step's
`tool_call_id` before appending the new one — replacing the stale attempt's
result rather than accumulating both.
`tests/test_graph_observe.py::test_retry_replaces_the_stale_tool_message_instead_of_duplicating_it`
covers it directly and was mutation-verified the same way (revert to
appending unconditionally → red, naming exactly that test → revert back →
green, 85 passed). Re-ran the live retry scenario after the fix:
`final_answer: "47 times 89 is 4,183."` — correct.

**Mutation-test evidence for the tests this ADR's own reasoning depends on**
(per ADR-007's standard — a test file cannot prove itself trustworthy from
inside itself):

- `tests/test_llm_failover.py`: mutating `FailoverProvider` to swallow the
  primary's transient error and fabricate a response (never calling the
  fallback) turned exactly 5 of 7 tests red, by name
  (`test_transient_primary_failure_falls_over_to_fallback` x3,
  `test_fallback_failure_propagates_without_a_second_retry`,
  `test_messages_and_tools_are_forwarded_unchanged_to_the_fallback`) — the 2
  that stayed green were the ones that don't involve a transient failure at
  all, exactly as expected. Separately, mutating the `except` clause to a
  blanket `except Exception` (violating ADR-002's narrow-catching
  requirement) turned exactly 1 test red —
  `test_non_transient_primary_failure_is_not_caught_and_fallback_is_never_called`
  — confirming that specific guarantee has real coverage, not just the
  happy path. Reverted both mutations; confirmed clean diff and 7/7 green.
- `tests/test_graph_tool_selection.py`: mutating `tool_call_node` to always
  resolve `"calculator"` regardless of the plan step's actual tool name
  turned 3 of 5 tests red (`[web_search-...]`, `[notes_store-...]`, and
  `test_multi_step_plan_invokes_each_tool_in_order`) — the calculator case
  stayed green by coincidence (it already resolved to calculator), exactly
  as expected. This mutation exercise also caught a real, unrelated wiring
  bug independent of the test's own logic: `build_graph`'s
  `add_conditional_edges` `path_map` for `decide_next` was keyed on the
  pre-translation `next_action` labels ("advance", "retry", "replan") when
  `route_after_decide` actually returns already-translated node names — a
  `KeyError: 'delegate'` on the very first multi-step plan, caught by
  `test_multi_step_plan_invokes_each_tool_in_order` before any mutation was
  even applied. Fixed the `path_map` to key on the actual node names.
  Reverted the deliberate mutation after; confirmed clean diff and 5/5
  green.

**Decision:** treat a real end-to-end run as a required gate for any graph
change that touches message-history construction, not just an optional
sanity check — the two bugs above both involved LangChain message-object
shapes (`AIMessage.content`'s type, valid tool-call/tool-response pairing)
that are straightforward to get subtly wrong by hand and that a
scripted/mocked `LLMResponse` test double cannot catch by construction,
since the test double never constructs a real `AIMessage` at all.

**What we gave up**

- Both live runs cost real Gemini API calls (free tier, not rate-limited
  today, so no budget concern) but are not part of CI — they're manual,
  run-and-paste-the-output verification, same as ADR-006's original
  end-to-end check. Nothing currently *enforces* that a future graph change
  re-runs this gate; it's a documented discipline, not a CI gate. Automating
  a real-API smoke test in CI is a real option but was ruled out for now —
  it would either burn API quota on every push or need to be marked
  allowed-to-skip, undermining its value as a gate.
  Zero real OpenRouter calls were needed for this ADR's verification (both
  live bugs were found via Gemini calls) — combined with the one OpenRouter
  call spent on this morning's model-liveness check, Day 2 used 1 of the
  50/day OpenRouter budget.
- Mutation testing here, as in ADR-007, is a manual practice applied to this
  day's new tests — nothing automatically re-runs it if these tests are
  later modified. A test edited after today could silently regress to
  "passes but doesn't test anything" without anyone noticing, the same gap
  ADR-007 flagged and didn't close either.

---

## ADR-014: Persistence architecture — LangGraph's native Postgres checkpointer for graph state, raw psycopg (no ORM) for the hand-designed schema

**Date:** 2026-08-24 (Day 3)

**Context**

ARCHITECTURE.md §3 step 5 requires that a paused approval "literally ends"
the graph run and is resumed later by a *separate* `POST
/approvals/{id}/approve` request — not held open in memory. That's a real
persistence problem: the in-progress plan, message history, retry/replan
counters, and everything else in `GraphState` has to survive across two
unrelated HTTP requests, possibly handled by different worker processes.

ADR-001 picked LangGraph specifically citing "built-in persistence/
checkpointing... human-in-the-loop checkpoints" as the deciding factor over
CrewAI. Day 3 is the first day that claim gets exercised for real rather
than staying a design intention.

**Decision (1): use LangGraph's own `interrupt()` / checkpointer mechanism, not a hand-rolled resume.**

Verified live, end to end, against the real Supabase Postgres instance
*before* writing any application code around it (not assumed from
documentation): installed `langgraph-checkpoint-postgres` (current PyPI
version 3.1.2, queried live) and `psycopg[binary]` (see "what we gave up"
below for why `[binary]`), ran `PostgresSaver.setup()` against the real
`DATABASE_URL`, confirmed it created its own `checkpoints` /
`checkpoint_blobs` / `checkpoint_writes` / `checkpoint_migrations` tables,
then built a throwaway two-node graph with an `interrupt()` call and proved
the exact pattern Day 3 needs: `compiled.invoke(...)` pauses and returns
`__interrupt__`; a **second, independently-constructed** `PostgresSaver` +
compiled graph (simulating a fresh process handling the follow-up HTTP
request) resumes correctly via `compiled2.invoke(Command(resume=...),
config=...)`, reading only from the persisted checkpoint. Confirmed working
with both a bare `psycopg.Connection` and the `psycopg_pool.ConnectionPool`
the app actually uses (`autocommit=True`, `row_factory=dict_row`).

This validates ADR-001's original justification with real usage rather than
leaving it a documentation claim — the graph module (`app/graph/`) needed
zero structural changes to support pausing; `approval_gate_node` (ADR-015)
is the only node that calls `interrupt()`.

**Decision (2): no ORM for the five hand-designed tables (`sessions`,
`messages`, `trace_events`, `pending_actions`, `session_memory`).**

`app/repository.py` is raw parameterized SQL via `psycopg`, not SQLAlchemy.
The query shapes are simple CRUD plus two conditional-update guards (see
ADR-015); introducing an ORM's session/model/migration machinery for five
small tables would be more code to maintain than the SQL it would generate.
SQL migrations live in `backend/migrations/*.sql`, applied by a small
tracking script (`scripts/migrate.py`, a `schema_migrations` table +
apply-in-order-once) — deliberately manual, run by a developer (or a future
Day 6 deploy step), not auto-run on app boot, which would race multiple
workers migrating concurrently for no benefit at this scale.

This also means the `supabase` Python client package ADR-004 pinned back on
Day 1 ("Database... wired up starting Day 3") went unused — that package is
Supabase's REST/Storage/Auth SDK, not a Postgres driver, and everything
Day 3 needed is direct SQL over the connection string already in
`DATABASE_URL`. Removed from `requirements.txt` rather than left as a
dangling unused dependency; correcting the record here rather than editing
ADR-004's original text, same convention as ADR-008.

**Two real bugs found only by running this against the real database, not
by any earlier design review:**

1. **`tool_args` silently failed to adapt as `jsonb`.** psycopg3 does not
   auto-adapt a plain Python `dict` to a `jsonb` column — the first live run
   of `create_pending_action` raised
   `psycopg.ProgrammingError: cannot adapt type 'dict'`. Fixed by wrapping
   with `psycopg.types.json.Jsonb(tool_args)` at the one call site that
   inserts it. `tests/test_repository.py::test_pending_action_jsonb_args_round_trip`
   covers this directly with a nested dict, against the real column.
2. **`ToolCallRequest` (part of checkpointed `GraphState.plan`) triggered
   `Deserializing unregistered type app.llm.base.ToolCallRequest ... This
   will be blocked in a future version`.** LangGraph's checkpoint
   serializer reconstructs custom classes through an allowlist gate for
   security (arbitrary-class deserialization is the same class of risk as
   unpickling untrusted data); any class outside its own built-in safe list
   hits this gate, warn-but-allow by default today. Converting
   `ToolCallRequest` from a `@dataclass` to a Pydantic v2 `BaseModel`
   *looked* like the fix (LangChain's own Pydantic-based messages never
   trigger this warning) but verified directly that it wasn't sufficient by
   itself — Pydantic v2 models get a distinct wire encoding
   (`EXT_PYDANTIC_V2`) but go through the *identical* allowlist check on the
   way back out, confirmed by reading `jsonplus.py`'s `_check_allowed`
   directly. The actual fix: construct the serializer with
   `allowed_msgpack_modules=[("app.llm.base", "ToolCallRequest")]` explicitly
   (`app/graph/serde.py`, `GRAPH_SERDE` — used by every checkpointer
   construction site, including tests' `InMemorySaver`) . Verified live: the
   warning is gone from a real end-to-end run after this change, confirmed
   by re-running the exact same API smoke sequence that first surfaced it.
   The Pydantic conversion was kept anyway — it's more consistent with the
   rest of the codebase's value types and is what makes the dedicated
   `EXT_PYDANTIC_V2` path apply at all, even though the allowlist is what
   actually silences the warning.

**What we gave up**

- `psycopg[binary]` bundles a compiled `libpq` rather than linking the
  system one — simpler and more portable (no system `libpq` install step on
  Windows dev machines or Render's container), at the cost of not picking up
  OS-level `libpq` security patches automatically. psycopg's own docs flag
  this as fine for most use cases but not ideal for high-security production
  deployments; acceptable here given this is a free-tier portfolio deploy,
  not a scenario the trade-off is designed to warn against.
- LangGraph's checkpoint tables are keyed by `thread_id` (a plain string,
  set to `str(session_id)`) with **no foreign key back to `sessions`** —
  deleting a `sessions` row cascades to its `messages`/`trace_events`/
  `pending_actions`/`session_memory` children but leaves that session's
  checkpoint rows orphaned in `checkpoints`/`checkpoint_blobs`/
  `checkpoint_writes` forever. Caught directly during testing: 191 orphaned
  rows accumulated in `checkpoints` from test runs before any cleanup
  existed. Tests now explicitly call `checkpointer.delete_thread(str(session_id))`
  in teardown; there is no equivalent for real sessions in production yet —
  no `DELETE /sessions/{id}` endpoint exists (out of Day 3's explicit
  endpoint list), so a real deploy's checkpoint tables grow unbounded today.
  Worth real attention before Supabase's 500MB free-tier storage cap becomes
  a concern (ADR-003) — flagged here rather than silently deferred.
- Migrations are not run automatically in CI or on deploy — `scripts/migrate.py`
  was run manually against the shared dev/CI Supabase project for Day 3's
  schema. A schema change that ships without someone remembering to run it
  would cause CI's DB-backed tests to fail loudly (a missing column/table is
  a clear SQL error, not a silent pass) — safe-but-manual, not
  safe-and-automatic. Revisit if this project ever has more than one
  contributor or a real staging/prod split.
- One shared Supabase project for local dev AND CI (`DATABASE_URL` and
  friends added as GitHub Actions secrets from the same values in the local
  `.env`) — no isolation between a developer's local test run and CI's.
  Mitigated by every DB-backed test cleaning up its own rows in a `finally`
  block (verified: all five application tables plus `checkpoints` read back
  to 0 rows after a full local test run), and by tests using freshly
  generated UUIDs so concurrent runs can't collide on identity, but two
  test suites running at literally the same moment could still see each
  other's transient state. Acceptable for a solo project at this stage; a
  real second (CI-only) Supabase project would remove the risk entirely at
  the cost of a second free-tier project to keep in sync schema-wise.

---

## ADR-015: Human-in-the-loop approval — `pending_actions` as the HTTP-visible source of truth over an `interrupt()`-gated node

**Date:** 2026-08-24 (Day 3)

**Context**

ARCHITECTURE.md §2 requires "a real state machine, not a UI-only gate:
`pending -> approved -> executed` or `pending -> rejected` (terminal)...
persisted in Supabase... so the frontend's approval modal is a view onto
this state, not the source of truth for it." ADR-014 established that
LangGraph's checkpointer is what makes the graph itself resumable — this
ADR is about the layer above that: how the HTTP API exposes and drives that
pause, and what "irreversible" means concretely (ADR-016 covers *which*
actions).

**Decision: a dedicated `approval_gate` node, separate from `tool_call`.**

`delegate -> approval_gate -> tool_call -> observe -> decide_next`.
`approval_gate_node` is a no-op pass-through for every step except one that
needs approval (ADR-016); for those, it calls `interrupt({"tool_name":...,
"tool_args":..., "step_id":...})` and, on resume, either lets execution
continue (approved) or sets `last_failure`/`last_failure_transient=False`
(rejected) so `decide_next` (ADR-012) routes a rejection through the exact
same re-plan-or-give-up path as any other permanent step failure — no
separate "what happens after a rejection" logic needed.

This is a separate node rather than a check inside `tool_call_node`
specifically because of how LangGraph resumes: a node's *entire function
body* re-runs from the top on resume (only `interrupt()` itself
short-circuits via the replayed value — nothing about node boundaries is
checkpointed mid-function). Keeping the gate in its own tiny, idempotent
node means only that small check re-executes on resume, not `tool_call`'s
counter increments or `tool.run()` side effects. Verified directly this
matters, not just in theory: a mutation test (see below) reintroducing the
alternative (a `last_failure` check inside `tool_call_node` without properly
resetting it on retry) produced a real bug where a transient-failure retry
silently never re-ran the tool.

**Decision: `pending_actions` rows are created and resolved by the API
layer, not the graph.** `tool_call_node`/`approval_gate_node` know nothing
about Postgres — `app/session_runner.py` is the one place that reads
`result["__interrupt__"]` after an `.invoke()` call, creates the
`pending_actions` row from the interrupt payload, and sets
`sessions.status = 'awaiting_approval'`. `POST /approvals/{id}/approve` and
`.../reject` look up the row, apply `decide_pending_action` (a
`WHERE status = 'pending'` guard — a second decide on an already-decided
row is a 409, not a silent double-apply, verified directly with a
double-approve test both at the repository layer and through the real API),
then call `resume_session_run` with `Command(resume=True|False)`.
`mark_pending_action_executed` fires immediately after a successful
*approved* resume — "executed" means specifically "the tool this
pending_action named was attempted," independent of whether the rest of
that session's run goes on to succeed or fail further down the line.

**Decision: session status lifecycle is `created -> running -> (awaiting_approval <-> running)* -> done | failed`,**
and `POST /sessions` creates a session with **no task yet** — matching
ARCHITECTURE.md §3's literal ordering ("User sends a message via `POST
/sessions/{id}/messages`" as the first real action). The first
`POST /sessions/{id}/messages` call supplies the task and starts the graph
(`repo.start_session`, guarded to only succeed from `'created'`); a second
message to a session that's already running, paused, or finished is a
clear `409`, not a silent no-op or an implicit new unrelated run — Day 3's
graph design (ADR-012) is one task, one plan, per session; true multi-turn
re-planning from a fresh unrelated message is out of scope here (revisit
Day 4+ if the chat UI needs it).

**Verified live**, both through unit/graph-level tests (`InMemorySaver`,
scripted LLM and tools — fast, no real infra) and through the real API
against real Gemini and real Postgres
(`tests/test_integration_session.py::test_full_session_through_the_real_api_including_approval`):
create session -> message pauses at `awaiting_approval` with a real
`pending_actions` row -> a second message is rejected with 409 -> approve
resumes and completes -> a second approve on the same id is rejected with
409 -> the note is actually persisted in `session_memory`. Also observed
live (not scripted): rejecting a pending action and letting the real,
non-deterministic Gemini re-plan sometimes leads to *another* approval
pause (the re-plan proposed a different note write) — handled correctly by
the exact same mechanism with no special-casing, matching
`tests/test_graph_approval.py::test_two_write_steps_each_pause_independently`'s
scripted coverage of the same shape.

**What we gave up**

- No endpoint lists a session's pending action(s) directly — a client has
  to already know the `pending_action_id` (from the interrupt it received,
  or by reading the trace) to approve/reject it. Day 3's explicit endpoint
  list doesn't include one; Day 4's approval-modal UI will need to decide
  whether it wants `GET /sessions/{id}` to embed the current pending action
  inline, or a new endpoint — deferred rather than guessed at now.
- A session can pause for approval multiple times across its run (each
  irreversible step gets its own gate), but there is no cap on how many
  times a single run can re-plan into *another* approval-requiring step —
  only `MAX_REPLANS = 1` (ADR-012) bounds total re-plans, which already
  covers this indirectly, but there's no approval-specific budget separate
  from that shared one. Not a gap in practice today (one re-plan means at
  most two approval-worthy attempts total), flagged in case that changes.

---

## ADR-016: What counts as "irreversible" in Day 3's tool set

**Date:** 2026-08-24 (Day 3)

**Context**

ARCHITECTURE.md §3 step 5 gates on "the step is irreversible (e.g. a write
that can't be undone)" without naming which of Day 2's three tools that
means. Of the three: `calculator` is pure computation (no side effect at
all); `web_search` is a read against an external index; `notes_store` has
one action, `write`, that persists data past the current step — `read` and
`list` are also reads. `write` is the only genuinely irreversible action in
today's tool set: a later step (or the user) can't tell the difference
between "this note was never written" and "it was written and nobody looked
at it," so an unwanted write is a real, silent state change, unlike an
unwanted read or computation which simply produced an answer nobody acts on.

**Decision:** a small, explicit table in the graph layer —
`IRREVERSIBLE_STEPS = {("notes_store", "write")}` (`app/graph/nodes.py`) —
checked by `(tool_name, arguments["action"])` membership. Not a flag on the
uniform `Tool` interface (`name`/`description`/`args_schema`/`run` — see
ARCHITECTURE.md §2 and Day 2's tools). Adding a fifth member to that
interface for a property exactly one of three tools needs, and only for one
of its three actions, is more surface than the current tool set justifies.

**What we gave up**

- If a future tool adds its own write/irreversible action, `IRREVERSIBLE_STEPS`
  needs a manual entry — nothing enforces that a new irreversible action
  gets approval-gated by construction; forgetting is a silent gap, not a
  loud error. A per-Tool `irreversible(args) -> bool` method would make this
  structural instead of a table someone has to remember to update, at the
  cost of every tool (including the two that never need it) carrying the
  concept. Revisit if a second tool ever needs write-approval semantics —
  right now this would be speculative machinery for a single case.
- `notes_store`'s `write` action is irreversible in the sense that matters
  here (a silent, unreviewed state change), not in the stronger sense of
  "cannot be undone by any means" — the note itself can be overwritten by a
  later write to the same key. The approval gate protects against *an
  unreviewed write happening at all*, not against notes generally being
  mutable once written.

---

## ADR-017: `_env_file=None` never meant what the test suite's own docstrings claimed — real environment variables were never isolated

**Date:** 2026-08-24 (Day 3, post-CI-secrets correction)

**Context**

Adding `DATABASE_URL`/`GEMINI_API_KEY`/etc. as real GitHub Actions secrets
for Day 3's DB-backed and integration tests (ADR-014) broke 7 previously-
green tests in CI within minutes of the first push: four in
`test_health.py` (`test_readiness_not_ready_when_nothing_configured` and
three siblings) and three in `test_config.py`
(`test_env_file_none_ignores_real_dotenv_even_when_present`,
`test_settings_loads_an_explicit_env_file_path_regardless_of_cwd`,
`test_settings_reads_repo_root_env_when_started_from_backend`) — all with
the same shape: a test built to assert "nothing configured" or "this exact
fake value" instead got back a real key.

**What was actually true, verified directly against the CI failure logs and
reproduced locally (not assumed from the pydantic-settings docs):**
`_env_file=None` disables exactly one source — the dotenv file. It does
nothing to stop pydantic-settings from reading real OS environment
variables, which is a **separate, higher-precedence source** it always
consults. Worse: a real environment variable for a field wins over an
**explicit** `_env_file`'s content for that same field too — true whether
`_env_file` is `None`, a real path, or a throwaway fake path built inside a
test's own `tmp_path`. `conftest.py`'s `make_client` and three tests in
`test_config.py` all silently depended on "no test environment has these
env vars set" being true — which held, by coincidence, on every machine and
CI runner this project had used through Day 2, and stopped holding the
moment Day 3 gave the CI job real secrets for an unrelated reason (DB
access). `test_env_file_none_ignores_real_dotenv_even_when_present`'s own
docstring claimed `_env_file=None` "must keep meaning 'ignore any .env
entirely'" — narrower and wrong: it was never about `.env`-the-file being
the only other source.

This is the same shape of gap ADR-007 named on Day 1 — a test's claim was
broader than what it actually verified — just discovered by a real
environment change instead of a deliberate mutation test, and in Day 1's
original test suite rather than something written this session.

**Decision:** stop relying on "no relevant env var happens to be set" as an
implicit assumption. `tests/conftest.py` now derives
`SETTINGS_ENV_VAR_NAMES` directly from `Settings.model_fields` (so a new
field can't silently fall outside the isolation) and an `isolate_settings_env(monkeypatch)`
helper that `monkeypatch.delenv`s every one of them. `make_client` calls it
before constructing any `Settings(_env_file=None, ...)`. The three affected
`test_config.py` tests call it too (or, for the subprocess-based test, pass
an explicit `env=` with those names stripped from a copy of the parent's
environment, since `subprocess.run` inherits the parent's environment by
default otherwise).

**Verified both directions, exactly reproducing the CI failure locally
first:** ran the affected tests locally with the real `.env`'s values
exported as real shell environment variables (`set -a && source ../.env`)
— all 7 failed with the identical assertions CI showed. Applied the fix —
all 7 passed, still with those real env vars exported. Then mutation-tested
the fix itself: reverted `make_client` to drop the `isolate_settings_env`
call (env vars still exported) — the exact same 4 `test_health.py` failures
came back, named identically. Reverted the mutation; confirmed clean diff
and the full suite green both with and without the env vars exported.

**What we gave up**

- `isolate_settings_env` clears env vars for the *current test's* Settings
  construction — it doesn't (and can't, cheaply) prove no OTHER untested
  code path in the app makes the same "nothing configured" assumption
  outside a test context. `get_settings()`'s `@lru_cache` singleton is
  built once per real process from the real environment (correct — that's
  its whole job) and was never in question here; the gap was specific to
  test fixtures asserting on an empty baseline.
- This was caught because CI happened to add exactly the env var names
  these tests were sensitive to, in the same week. A quieter version of
  this gap — a test asserting on a field CI's secrets don't happen to
  cover — could still exist undetected. Deriving the isolation list from
  `Settings.model_fields` (rather than hand-naming the 7 that broke) is
  what protects against that going forward, not a guarantee nothing else
  is missed today.

---

## ADR-018: `GET /sessions` and an embedded `pending_action` — the two API gaps ADR-015 deferred, resolved now that the UI shape is known

**Date:** 2026-08-24 (Day 4)

**Context**

ADR-015's "what we gave up" flagged two things explicitly as deferred until
Day 4: no endpoint listed sessions at all, and no endpoint told a caller
*which* pending action was blocking a given session without already
knowing its id. Building the session-list page and the approval modal is
what finally answers "what does the UI actually need."

**Decision:** `GET /sessions` (most-recently-created first, no pagination
cursor — a plain list is all a single-page session list needs at this
scale) via a new `repo.list_sessions`. `SessionResponse` gains a
`pending_action: PendingActionResponse | None` field, populated whenever
`status == "awaiting_approval"` via a new `repo.get_pending_action_for_session`
(at most one "live" pending row per session, since the graph itself blocks
on `interrupt()` until it's decided — ADR-015) — moved to a shared
`app/api/schemas.py` since both routers need the same shape now.

**Decision: `POST /approvals/.../approve` and `.../reject` now return the
session, not the bare decided `pending_action`.** The frontend deciding an
approval needs to know what happens *next* — done? failed? paused again on
a different pending action, which live verification during Day 3 already
showed can happen for real (a rejection's re-plan proposing another write)?
The decided action alone can't answer that without a second `GET
/sessions/{id}` call the session-embedding response now makes unnecessary.
`session_with_pending_action` (in `app/api/sessions.py`) is the one place
that assembles this shape; `approvals.py` imports and reuses it rather than
duplicating the embedding logic.

**What we gave up**

- No `DELETE /sessions/{id}` endpoint yet, so the session list has no way
  to clean up old sessions from the UI — combined with ADR-014's flagged
  gap (checkpoint rows have no FK to `sessions` and aren't cleaned up
  either), a real deploy's session list only grows. Out of Day 4's
  explicit scope (chat UI, trace viewer, approval modal, session list —
  not session management), revisit if the list gets unwieldy in practice.
- `list_sessions`'s `LIMIT 50` with no cursor means a session list beyond
  50 silently truncates rather than paginating — acceptable for a
  portfolio demo's realistic session count, not a real multi-user product's.

---

## ADR-019: Frontend architecture — synchronous refetch over polling, `react-router-dom`, and a text-heuristic trace-tone

**Date:** 2026-08-24 (Day 4)

**Context**

Day 3's API is fully synchronous: `POST /sessions/{id}/messages` and `POST
/approvals/{id}/approve|reject` each block until the graph either finishes
or hits its next `interrupt()` (ADR-014/015). The frontend's whole
architecture follows from taking that seriously rather than building
infrastructure for a streaming/async backend that doesn't exist.

**Decision: no polling, no websockets — a mutating action's own response,
plus one follow-up fetch of the trace, is the entire update mechanism.**
`sendMessage`/`approvePendingAction`/`rejectPendingAction` each return the
fresh `Session` directly; `SessionPage.runAction` always re-fetches
`GET /sessions/{id}/trace` afterward too, since `state["trace"]` (ADR-012)
grows with every node the run touched and the frontend has no way to
reconstruct that from the session response alone. A loading/"Thinking…"
state covers the real several-second wait for a genuine Gemini call
(verified live: the happy-path call and the approval-resume call each took
a few real seconds end to end, not an instant mock).

**Decision: `react-router-dom` (7.18.2, current on npm, verified live) for
two routes** — `/` (session list) and `/sessions/:sessionId` (chat + trace
+ approval). `SessionPage` is deliberately remounted, not just re-rendered,
on `sessionId` change: it's rendered through a tiny `SessionPageRoute`
wrapper that reads the param and passes it as `key={sessionId}` to
`SessionPage` itself. This was not a stylistic choice — the first version
called `setLoad({state:'loading'})` directly inside `SessionPage`'s own
effect to reset state on navigation, which `eslint-plugin-react-hooks`'
`set-state-in-effect` rule correctly flagged, and which had a real bug
underneath the lint warning: without a full remount, `submitting` and
`actionError` from a PREVIOUS session would still be set when a user
navigated straight to a new one, until the next fetch resolved. The `key`
trick fixes both at once by letting `useState`'s own initializer do the
resetting.

**Decision: the trace viewer's color-coding is a text-content heuristic
(`toneFor` in `TraceViewer.tsx`), not a structured signal from the
backend.** `trace_events.detail` is a free-text string written by
`app/graph/nodes.py` for a human reading the trace directly (Day 2/3) —
substrings like `"FAILED (transient)"`, `"REJECTED"`, `"-> finalize"` are
what `toneFor` matches on to decide warning/error/success coloring, since
the backend doesn't (and, given ADR-012's `trace` list is exactly the
free-text log design already committed to, wasn't going to before Day 4)
emit a separate structured severity field.

**What we gave up**

- The trace's warning/error/success coloring is coupled to the exact
  wording `nodes.py` writes into `detail` — a future change to that
  wording (e.g. rewording "FAILED (transient)") silently drops back to the
  default/neutral tone rather than erroring, since `toneFor` has no way to
  know the string it expected stopped appearing. A structured `severity`
  field on `trace_events` (set at the point each event is created, not
  inferred from prose after the fact) would be more robust and was
  considered, but adding a column and updating every `add_trace_event`
  call site for a Day 4 cosmetic concern was judged more than this
  feature needs today — revisit if the trace viewer grows more
  sophisticated filtering/search on top of tone.
- No live/streaming trace updates while a message or approval request is
  in flight — a real Gemini call with several tool-call steps runs
  entirely server-side before the frontend sees anything beyond
  "Thinking…", so a genuinely long multi-step run gives no incremental
  feedback. Server-sent events or WebSockets would fix this but need a
  non-synchronous backend request model this project hasn't built
  (ADR-014's endpoints are all request/response); out of Day 4's scope.
- `ApprovalModal` re-renders fresh (its `reason` textarea resets) any time
  its parent re-renders with a new `pendingAction` object identity, since
  there's no explicit key tying the modal to a specific pending action id.
  In practice this only matters if a session could show two DIFFERENT
  pending actions without an intervening unmount, which the one-pending-
  action-at-a-time invariant (ADR-015) rules out — flagged as a assumption
  the component relies on rather than something it enforces itself.

---

## ADR-020: Atomic result application, sequenced traces, and tool-boundary execution records

**Date:** 2026-08-27 (reliability-foundation sprint)

**Context**

The Day 3 persistence bridge applied one graph result through several
independently committed repository calls. A failure could leave trace rows or a
pending action committed without the corresponding session transition. Trace
resume logic also inferred the next event from the number of stored rows, and
approval handling marked an action `executed` before checkpoint loading began.
Those behaviors made the audit trail—the product's central promise—least
reliable on precisely the failure paths where it matters most.

**Decision: all application-table writes for one graph result share one explicit
PostgreSQL transaction.** Repository operations used by `_apply_result` accept
the transaction's existing connection. A write failure rolls back trace rows,
messages, pending actions, and session status together. Status-only updates do
not overwrite `final_answer`, and a graph exit with neither an interrupt nor a
terminal state is treated as an error rather than silently leaving `running`.

**Decision: trace identity is `(session_id, sequence)`.** Every graph node
creates a typed event with a monotonic sequence, structured level, and optional
provider. Persistence uses `ON CONFLICT DO NOTHING`, making a replay
idempotent. The frontend consumes `level`; detail-text parsing remains only for
legacy rows. Migration `0003` backfills existing sequences in original row
order before enforcing uniqueness.

**Decision: `executed` means the irreversible tool attempt has begun.** The
approval endpoint records the human decision but does not mark execution. It
passes a narrow callback into the graph, and `tool_call` invokes that callback
after resolving the tool and immediately before calling it. Failures before
the node leave the action `approved`; classified tool failures after the
boundary leave it `executed` because an attempt genuinely occurred.

**Decision: ordinary CI is deterministic and secret-free.** GitHub Actions
uses an isolated pgvector/PostgreSQL service, runs migrations, and excludes
tests marked `live`. A manual workflow owns external-provider smoke tests.
Mypy and strict TypeScript checks are required alongside the existing lint,
test, and build gates.

**What we gave up**

- LangGraph checkpoint commits and application-table commits remain separate.
  They are controlled by different persistence layers and cannot share one
  transaction. Sequence-based idempotency makes recovery safe, but does not
  pretend the cross-system boundary is atomic.
- If an external side effect succeeds and the process dies before the
  `executed` database transition commits, perfect exactly-once knowledge is
  impossible without a tool-specific idempotency key or transactional outbox.
  The current transition is placed immediately before invocation because it
  avoids falsely reporting execution when checkpoint loading fails and gives
  the most truthful state available with this schema.
- Live provider behavior is no longer exercised on every pull request. The
  manual smoke workflow preserves that coverage without making forks, quotas,
  or third-party outages part of the correctness gate.

---

## ADR-021: Single-operator API security and lifespan-owned infrastructure

**Date:** 2026-08-28 (security-and-operations sprint)

**Context**

The application exposed quota-consuming and state-changing routes without an
authentication boundary, treated configured database strings as proof of
readiness, and let individual tool instances own network clients. That was
acceptable during local construction but unsafe for a public deployment.

**Decision: mutations use one explicit operator credential.** Every `POST`
requires `X-Agent-Ops-Key`, compared in constant time to the secret-valued
`AGENT_OPS_API_KEY` setting. Production refuses to start with a blank key.
The browser accepts the key at runtime and keeps it in `sessionStorage`; it is
never a build-time Vite variable. Read-only observability remains public for
the portfolio demo. Per-IP in-memory limits are appropriate because deployment
is deliberately single-instance.

**Decision: the application lifespan owns infrastructure.** Startup creates
the PostgreSQL pool and shared HTTP client; shutdown closes each once. Pool
connections are checked before handoff. Readiness now runs a timeout-bounded
`SELECT 1`, while liveness remains dependency-free.

**Decision: unexpected adapter exceptions become permanent step failures.**
Expected `ToolError` classification remains first. A final backstop records a
sanitized trace summary and a redacted traceback without persisting upstream
bodies, connection credentials, authorization headers, or tokens.

**Decision: the deployment artifact is a non-root multi-stage image.** Build
tooling remains in the builder stage; migrations and their runner ship in the
runtime stage; Docker health targets `/health`, not readiness.

**What we gave up**

- The browser-visible key identifies one operator, not individual users. It is
  an operational gate, not an account or authorization system.
- In-memory limits are per process. Horizontal scaling remains out of scope;
  distributed storage must be introduced before adding instances.
- Public read routes expose session/trace metadata by design. Revisit that
  threat model before storing sensitive end-user content.

---

## ADR-022: Optional failover is represented by provider composition, not empty credentials

**Date:** 2026-08-28 (release-candidate sprint)

**Context**

The primary Gemini provider is sufficient to serve requests, but the original
dependency factory always constructed an OpenRouter client. A valid
Gemini-only deployment therefore crashed during dependency construction even
though readiness deliberately classified it as degraded-but-serviceable.

**Decision**

Construct Gemini whenever its required settings are present. Construct and
wrap it in `FailoverProvider` only when both OpenRouter key and model are set;
reject half-configured fallback settings at application startup. The provider
factory's runtime shape now matches ADR-009's readiness semantics.

**What we gave up**

- A degraded deployment has no automatic provider failover until both optional
  OpenRouter settings are supplied.
- Provider construction remains process-cached; rotating a provider key needs
  a restart.

---

## ADR-023: Graph work and retry limits have one semantic source of truth

**Date:** 2026-08-28 (release-candidate sprint)

**Context**

Planner steps, tool calls, and retry attempts were previously bounded in
different nodes with overlapping counters. Boundary values could be accepted
by one node and rejected by the next, and calculator input could create work
far beyond the graph's nominal step bound.

**Decision**

Keep graph bounds in `app/graph/limits.py` and define counters by completed
work: a step/tool call is allowed only while the completed count is below its
maximum. Retry counts advance exactly once per failed attempt. Tool adapters
also enforce their own input-complexity bounds because graph limits cannot
make one individual operation safe.

**What we gave up**

- Limits are fixed deployment policy, not per-session user configuration.
- A task that genuinely needs more work fails clearly instead of extending a
  run dynamically.

---

## ADR-024: Structured trace metadata supersedes ADR-019's text heuristic

**Date:** 2026-08-28 (release-candidate sprint)

**Context**

ADR-019 inferred trace tone from words inside free-form detail text. That made
presentation depend on copy and could not reliably expose provider failover or
deduplicate replayed graph events.

**Decision**

Every new trace row carries a monotonic per-session `sequence`, a structured
`level`, and the producing `provider` when applicable. Persistence uses
`(session_id, sequence)` for replay idempotency, and the UI renders `level`
directly. Text inference remains only as a compatibility fallback for rows
created before structured levels existed; this decision supersedes that part
of ADR-019.

**What we gave up**

- Old rows cannot be perfectly reconstructed; their heuristic presentation is
  retained rather than rewritten.
- LangGraph checkpoints and application trace rows remain separate commits, as
  already accepted in ADR-020.
