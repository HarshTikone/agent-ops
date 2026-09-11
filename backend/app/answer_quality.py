"""What counts as a usable final answer — one definition, two callers.

`finalize_node` (`app/graph/nodes.py`) calls this at runtime to decide whether
a model's answer may be shown to a user, and `scripts/audit_sessions.py` calls
the same function offline to grade sessions that already ran. Sharing one
implementation is the whole point: an audit that applied looser rules than the
runtime guard would go green on precisely the sessions the guard exists to
catch.

Two failure shapes have actually reached production (2026-09-11 audit of the
live deployment), and they are what the rules below encode:

1. **An empty string.** A provider can answer HTTP 200 with no text. That is
   not an exception, so `FailoverProvider` never sees it — it only catches
   `TransientProviderError` (ADR-002) — and the pre-fix `finalize_node` stored
   the empty content verbatim while stamping the trace event `level="success"`.
   Three of eighteen `done` sessions in production carry an empty answer.
2. **Raw tool-call markup.** Asked to summarize with `tools=None`, a model may
   still emit tool-call syntax as plain text. Session `A675` — recorded in the
   project notes as verified — shipped `<tool_call><function=notes_store>…` to
   the user as its final answer.

Both were reported as successes, which is why the check lives here rather than
inside a single node: the definition of "usable" needs to be assertable from a
test and from a backfill script, not just reachable at runtime.
"""

from __future__ import annotations

import re

# An answer shorter than this is not a summary of anything. Deliberately low —
# the job here is catching degenerate output ("ok", ".", "1289.4"), not making
# an editorial judgement about brevity.
MIN_ANSWER_CHARS = 12

# Markup a model emits when it tries to call a tool in plain prose. Matched
# case-insensitively and anywhere in the string: an answer that is mostly prose
# with one of these appended is still leaking protocol into the product, and is
# still the wrong thing to show someone.
_TOOL_MARKUP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<\s*/?\s*tool_call\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*function\s*=", re.IGNORECASE),
    re.compile(r"<\s*/?\s*parameter\s*=", re.IGNORECASE),
    re.compile(r"<\s*\|[^|>]*tool[^|>]*\|\s*>", re.IGNORECASE),
)

_MARKUP_PLACEHOLDER = "[tool-call markup removed]"


def validate_answer(text: str | None) -> str | None:
    """Return a short rejection reason, or `None` when the answer is usable.

    Returning a reason string rather than raising keeps this usable from three
    places with different needs: the graph node wants to branch on it, the
    audit script wants to print it, and the tests want to assert on it.
    """
    if text is None:
        return "answer is null"

    stripped = text.strip()
    if not stripped:
        return "answer is empty"

    for pattern in _TOOL_MARKUP_PATTERNS:
        if pattern.search(stripped):
            return "answer contains raw tool-call markup"

    if len(stripped) < MIN_ANSWER_CHARS:
        return f"answer is shorter than {MIN_ANSWER_CHARS} characters"

    return None


def is_usable(text: str | None) -> bool:
    """Convenience predicate over `validate_answer`."""
    return validate_answer(text) is None


def scrub_tool_markup(text: str) -> str:
    """Neutralize tool-call markup so quoted text can't fail its own check.

    The deterministic fallback answer (see `nodes.py`) quotes raw tool output.
    A tool that happened to return something markup-shaped would otherwise make
    the fallback itself invalid — the one answer that must always pass.
    """
    scrubbed = text
    for pattern in _TOOL_MARKUP_PATTERNS:
        scrubbed = pattern.sub(_MARKUP_PLACEHOLDER, scrubbed)
    return scrubbed
