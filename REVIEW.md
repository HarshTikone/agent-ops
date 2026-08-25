# Review — 2026-08-25 — diff `git diff HEAD` (uncommitted, Phase 1 only)

**Scope:** working-tree changes on top of `d4df774` (tag `day-4-complete`) — an
attempt at Phase 1 of `reviews/day-4-fix-prompt.md` (the four Critical
findings from `reviews/day-4-review.md`). Files touched: `dependencies.py`,
`config.py`, `tools/calculator.py`, `graph/nodes.py`, `graph/limits.py`,
`api/approvals.py`, `api/sessions.py`, plus tests for all of the above and
new `tests/test_dependencies.py`.

**Method:** read every changed file in full, traced the logic by hand,
re-ran the relevant test subset and the full backend suite (both green, 127
passed / 0 skipped — DATABASE_URL is available locally so the DB-backed C4
tests actually executed, not skipped), and mutation-tested C3 by reverting
decide_next_node's cap check to sit above the finalize branch: the new test
failed by name (assert failed == done) exactly as it should, then restored
the file byte-for-byte and reconfirmed the full suite green. Also directly
reproduced the C4 gap described below with unittest.mock.patch against a
running TestClient (no source mutation needed there). ruff check . and
black --check . are both clean on the diff, including the new
test_dependencies.py.

---

## Critical

None found. C1, C2, and C3 are each fixed correctly, with tests that
actually exercise the regression (see verdicts below).

## High

### C4 is only partially fixed - a DB call adjacent to the wrapped run still permanently wedges the session/action

**File:** `backend/app/api/sessions.py:85` (`repo.add_message`) and
`backend/app/api/approvals.py:76` (`repo.mark_pending_action_executed`)

**Problem:** The fix correctly wraps `start_session_run`/`resume_session_run`
in try/except Exception, updating status to failed, writing a trace
row, and returning 502 - and this is verified end-to-end by real DB-backed
tests (test_provider_crash_during_send_message_leaves_session_failed_not_stuck,
test_provider_crash_during_resume_leaves_session_failed_and_action_executed).
However, in both endpoints there is exactly one more repository call that
runs after the session/action has already been flipped to a
non-terminal committed state, but before the try block starts, and
it is not covered:

- `sessions.send_message`: `repo.start_session` flips the row to running
  and commits, then `repo.add_message(...)` runs unwrapped, then the
  try begins around `start_session_run`.
- `approvals._decide`: `repo.decide_pending_action` commits approved (or
  rejected), then `if approve: repo.mark_pending_action_executed(...)`
  runs unwrapped, then the try begins around `resume_session_run`.

This reintroduces the exact failure mode C4 was written to close, just one
statement earlier - the same class of bug the review called out as "the
approval path is worse" (an action stranded at approved on a session
stuck at awaiting_approval), now reachable via a different, still
realistic trigger (a transient DB failure on that one write, the same kind
of "DB blip" the fix's own comments cite as a target failure mode for the
wrapped calls).

**Failure scenario (reproduced live, not hypothetical):**
Mocking `app.api.approvals.repo.mark_pending_action_executed` to raise
RuntimeError on an otherwise-normal approve call: the exception
propagates uncaught past `_decide` (no except, no trace row, no status
update); the session is left at status="awaiting_approval" and the
pending action at status="approved" - permanently, since there is no
retry path for an already-non-pending action and no path that ever
revisits this session. In production, with no global exception handler yet
(that's Phase 7, main.py), this surfaces as a bare unhandled-exception
500 with no detail, not the intended 502. Symmetrically, mocking
`app.api.sessions.repo.add_message` to raise: the session is left at
status="running" forever, and a retry to the same session hits the
WHERE status='created' guard and returns 409 - exactly the "409 trap"
C4's own comment describes as the bug being fixed.

**Fix:** widen the try in both endpoints to start before the unwrapped
call (i.e., wrap from `repo.add_message`/`repo.mark_pending_action_executed`
through the run call, in one try), or give each of those two writes its
own narrow try/except with the same failed-status/trace-row/502
handling. Add a test that injects a raising `repo.add_message` /
`repo.mark_pending_action_executed` (not just a raising provider) and
asserts the same failed + trace-row + 502 outcome.

## Medium

None found beyond the High item above - no new missing-error-handling or
edge-case gaps introduced by this diff outside the C4 residue already
covered.

## Low

### Code comments forward-reference an ADR-020 that doesn't exist yet

**File:** all seven touched source files reference ADR-020 by name
(config.py, dependencies.py, tools/calculator.py, graph/nodes.py,
graph/limits.py, api/approvals.py, api/sessions.py, plus the new
tests) as the record of these fixes and the live verification behind them.
ADR.md has no ADR-020 entry - the last numbered ADR is ADR-019
(referenced in the Day 4 review re: trace tone). This is consistent with
the fix-prompt's own phasing (docs land in Phase 7, "Write new append-only
ADRs for... the C2/C3 limit-semantics changes"), so it isn't a ground-rule
violation (ADR.md itself is untouched, not edited-in-place), just a
dangling reference until Phase 7 lands - worth not forgetting, since right
now a reader following the comment finds nothing.

---

## Verdicts

### C1 - Gemini-only deploy 500s at construction: FIXED

`dependencies.py:25` returns a bare GeminiProvider when
`openrouter_api_key` or `openrouter_model` is empty, with a clear one-time
`logger.warning`, before ever constructing OpenRouterProvider (so
ChatOpenAI's construction-time OpenAIError is never triggered).
`config.py` adds `_reject_half_configured_openrouter`, a `model_validator`
that raises ValueError at Settings() construction when exactly one of
the two is set - verified to actually fire at import time via `main.py:11`
(`settings = get_settings()` at module scope), matching "fail fast at
startup." Real tests: `test_dependencies.py` builds `get_llm_provider()`
with Gemini-only settings and asserts a bare GeminiProvider (not
FailoverProvider) comes back and does not raise; a both-set case asserts
FailoverProvider; `test_config.py` asserts ValidationError for both
half-configured directions. All pass against a real, uncached call
(`cache_clear()` is used correctly since `get_llm_provider` is
@lru_cache, which would otherwise mask the fix across test order).
`test_health.py`'s two fixtures needing `openrouter_model` added alongside
`openrouter_api_key` is the correct consequence of the new validator, not
scope creep.

### C2 - unbounded Pow DoS: FIXED

`calculator.py` adds `_MAX_EXPRESSION_LENGTH` (500), `_MAX_AST_DEPTH` (50,
checked in `_eval_node` before descending into any node type), and
`_check_pow_bounds` (a log2-based bit-length estimate checked before
`operator.pow` is ever called, not a post-hoc check on an already-computed
result). Verified by hand that this closes the specific reported inputs
without pathological gaps: `9**9**9` is right-associative
(9 ** (9 ** 9)), so the inner 9**9=387420489 computes trivially and the
outer check rejects at an estimated ~1.23 billion bits before operator.pow
runs; `2**(10**10)` similarly computes the cheap inner 10**10 then rejects
the outer at construction-cost-estimate time; a flat 10,001-char + chain
is rejected on length before ast.parse runs; a short-but-deep 80-term
+-chain (well under the length cap) is rejected by the depth counter, not
a raw RecursionError (fixing M8 as a side effect, with an explicit
except RecursionError added at both the parse and eval call sites as a
second line of defense). `2 ** 10` still returns "1024". Traced the
"could a Mult/Add chain achieve similar blow-up under the same character
budget" question by hand: no - unlike Pow, Mult/Add have no way to
compress "repeat this operation N times" into O(log N) characters, so
their achievable growth under a 500-char/depth-50 budget is bounded and
fast; this is not a gap. Tests assert a wall-clock bound
(_FAST_REJECTION_SECONDS = 2.0, docs note actual times are under 0.01s) on all
four required inputs, not just exception type - meeting the ADR-007
"a test that only asserts the exception type would pass against a version
that takes an hour to raise it" standard explicitly.

### C3 - successful MAX_TOOL_CALLS-step plan reported as failed: FIXED

The unconditional cap check at the top of `decide_next_node` is gone,
replaced by a `_give_up_on_cap` helper called from inside each of the three
"continue" branches (advance, retry, replan) - the finalize branch (plan
complete) is checked first and returns unconditionally before any cap
check runs. `limits.py`'s docstring states the precedence explicitly, as
required. New test drives the real compiled graph with exactly
MAX_TOOL_CALLS successful steps and asserts status == "done",
final_answer == "all done", and no cap-related trace event - this is
exactly the reproduction case from the review (step_index=9,
tool_calls_made=10, last_failure=None). The pre-existing sibling test
(cap reached with steps remaining -> give_up) still passes unmodified.
Mutation-tested directly: reverted the cap check to the old
unconditional-top-of-function position, reran the suite - the new test
failed by name with assert 'failed' == 'done', confirming it is a real
regression test, not decoration. Restored and reconfirmed all 127 tests
green afterward.

### C4 - exceptions wedge sessions permanently: PARTIALLY FIXED

The core of the fix is real and well-verified: both `send_message` and
`_decide` now wrap the run/resume call, and on exception update status to
failed with a real final_answer, write a trace_events row containing
"CRASH", `logger.exception(...)` the traceback, and raise
HTTPException(502). This is proven end-to-end by two real DB-backed
tests that inject a raising provider through FastAPI's
dependency_overrides and assert the session lands on failed, a trace
row exists, and the retry path behaves correctly (409, not a hang) - not
mocked at the unit level, an actual TestClient round trip against a real
database. The approval path's placement question (mark_pending_action_executed
moved to before the resume attempt) is a deliberate, documented choice
that correctly stops the originally reported strand scenario (resume
raising after being marked approved-but-not-executed).

However, as detailed in the High finding above, this doesn't close the
general case: `repo.add_message` and `repo.mark_pending_action_executed`
themselves are each one more DB write, unwrapped, sitting between the
already-committed state transition and the newly-added try block. A
failure at either exact point reproduces the identical wedge/strand
outcome C4 was written to eliminate, confirmed by direct reproduction
against the running app (not merely inferred). This is why the verdict is
partial rather than full.

---

## What's genuinely good

- The wall-clock-asserting test discipline in C2 is exactly right for a
  timing bug - a naive "asserts a ToolError was raised" test would still
  pass against a version that computes the huge result first and then
  rejects it, and the test file's own docstring says so.
- The C3 fix is minimal and correctly scoped - it doesn't restructure
  decide_next_node's branching, just moves one check to the right places
  and factors the shared behavior into _give_up_on_cap. Low blast radius
  for a correctness-critical function.
- The C1/C4 tests exercise the real get_llm_provider/TestClient/DB
  path, not mocks standing in for the thing being tested - consistent
  with this repo's established _FakeTransport-over-mocking standard, and
  it's why the C4 gap above was findable at all (the tests that exist are
  strong; the gap is a missing test, not a wrong one).
- The half-configured-OpenRouter validator (config.py) is the correct
  fail-fast fix, verified against a real main.py-level get_settings()
  call at import time rather than assumed.
- Ground rules were respected: no ADR.md/ARCHITECTURE.md edits, no
  migrations touched, no Day 5 scope, ruff/black both clean, diff is
  scoped exactly to the 12 files Phase 1 names.

## Not fixed (deliberate)

Nothing left open. The one High finding (C4's residual gap) was fixed:
`backend/app/api/sessions.py` now wraps `repo.add_message` inside the same
`try` as `start_session_run`, and `backend/app/api/approvals.py` wraps
`repo.mark_pending_action_executed` inside the same `try` as
`resume_session_run`. Two new regression tests
(`test_add_message_failure_leaves_session_failed_not_stuck`,
`test_mark_executed_failure_leaves_session_failed_not_stranded`) inject a
raising repository call via `unittest.mock.patch` and assert the session
lands on `failed` with a trace row and a 502 — both were mutation-tested by
reverting the fix and confirming they fail by name first. Full suite: 129
passed (127 + 2 new); `ruff check .` and `black --check .` clean.
