"""Retry/re-plan/give-up bounds (ADR-012).

An agent loop with no cap can burn a day's OpenRouter quota — or just spin
forever — in one runaway session. Three independent bounds, checked in this
order by `decide_next_node`:

1. `MAX_TOOL_CALLS` — a hard ceiling across the whole run, regardless of the
   other two counters. The backstop against a pathological loop (e.g. a
   re-plan that immediately re-triggers the same failure) rather than the
   primary mechanism.
2. `MAX_STEP_RETRIES` — how many extra attempts a single step gets before
   the failure is treated as un-retryable and handed to re-planning instead.
3. `MAX_REPLANS` — how many times the whole run is allowed to go back to the
   planner before giving up outright.
"""

MAX_STEP_RETRIES = 2
MAX_REPLANS = 1
MAX_TOOL_CALLS = 10
