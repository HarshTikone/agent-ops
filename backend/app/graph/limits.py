"""Retry/re-plan/give-up bounds (ADR-012, extended by P2).

An agent loop with no cap can burn a day's OpenRouter quota — or just spin
forever — in one runaway session. Three independent bounds, checked by
`decide_next_node` and `verify_node`:

1. `MAX_TOOL_CALLS` — a hard ceiling across the whole run, regardless of the
   other two counters. The backstop against a pathological loop (e.g. a
   re-plan that immediately re-triggers the same failure) rather than the
   primary mechanism.
2. `MAX_STEP_RETRIES` — how many extra attempts a single step gets before
   the failure is treated as un-retryable and handed to re-planning instead.
3. `MAX_PLANNING_ROUNDS` — how many times the whole run is allowed to go
   back to the planner before giving up outright. Originally `MAX_REPLANS`
   (1): only a failed, un-retryable step sent the run back to `planner`.
   P2 makes going back to `planner` the NORMAL way a multi-step task makes
   progress too (`verify_node` routes there whenever the task isn't done
   yet), so the same counter (`state["replans"]`) and budget now cover both
   reasons a run returns to the planner, raised to 4 rounds to give a real
   multi-step task room to iterate. `verify_node` is what keeps a task the
   tools genuinely cannot satisfy from burning through it in the first
   place: it gives up once THIS budget is spent, rather than spinning all
   the way to `MAX_TOOL_CALLS` first.

**Precedence (ADR-020, fixing C3): `MAX_TOOL_CALLS` gates CONTINUING, never
FINISHING.** It's checked only inside the advance/retry/replan branches,
immediately before each would consume another tool call — never
unconditionally ahead of the success/finalize branch. A plan that succeeds
on exactly its `MAX_TOOL_CALLS`-th step must still reach `verify`/`finalize`
and report `done`; the cap exists to stop a run that hasn't finished from
burning unbounded budget, not to retroactively fail one that just did.
"""

MAX_STEP_RETRIES = 2
MAX_PLANNING_ROUNDS = 4
MAX_TOOL_CALLS = 10
