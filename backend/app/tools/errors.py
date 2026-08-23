"""The one exception every tool adapter is allowed to raise.

`transient` mirrors the LLM layer's narrow-exception philosophy (ADR-002,
ADR-010) applied to tools: the graph's `decide_next` node needs to tell "this
looks like a network blip, retry the same step with the same args" apart from
"this step's args or tool choice were wrong — retrying identically will fail
identically, re-plan instead" (ADR-012). The adapter that raised the error is
in the best position to know which shape its own failure is.
"""

from __future__ import annotations


class ToolError(Exception):
    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient
