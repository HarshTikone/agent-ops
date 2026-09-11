"""Tests for the backfill audit.

Grading logic and report formatting are pure functions over session rows, so
none of this needs a database — `main()` is the only part that touches one.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.audit_sessions import (
    ANSWER_BEARING_STATUSES,
    audit_session,
    audit_sessions,
    format_report,
)

_GOOD = "The note was saved and read back with the value 'rls-fix-verified'."
_MARKUP = "<tool_call><function=notes_store><parameter=key>k</parameter></function></tool_call>"


def session_row(
    *,
    status: str = "done",
    final_answer: str | None = _GOOD,
    task: str = "Do the thing",
    session_id: str = "8e4d666c-a756-4dbc-b81b-d3cf5ba89fdf",
) -> dict[str, Any]:
    return {"id": session_id, "status": status, "final_answer": final_answer, "task": task}


class TestWhichSessionsGetGraded:
    @pytest.mark.parametrize("status", sorted(ANSWER_BEARING_STATUSES))
    def test_answer_bearing_statuses_are_graded(self, status: str) -> None:
        assert audit_session(session_row(status=status)) is not None

    @pytest.mark.parametrize("status", ["created", "running", "awaiting_approval", "failed"])
    def test_other_statuses_are_skipped(self, status: str) -> None:
        """A mid-flight or deliberately-failed session has nothing to grade."""
        assert audit_session(session_row(status=status, final_answer="")) is None

    def test_failed_sessions_are_not_counted_as_unusable(self) -> None:
        """`failed` carries an operator explanation, not a model answer."""
        rows = [session_row(status="failed", final_answer="Rejected and not executed.")]
        assert audit_sessions(rows) == []


class TestGrading:
    def test_usable_answer_passes(self) -> None:
        verdict = audit_session(session_row())
        assert verdict is not None and verdict.ok and verdict.reason is None

    def test_empty_answer_fails(self) -> None:
        verdict = audit_session(session_row(final_answer=""))
        assert verdict is not None and not verdict.ok
        assert verdict.reason == "answer is empty"

    def test_markup_answer_fails(self) -> None:
        verdict = audit_session(session_row(final_answer=_MARKUP))
        assert verdict is not None and not verdict.ok
        assert verdict.reason == "answer contains raw tool-call markup"

    def test_short_id_is_the_last_four_uppercased(self) -> None:
        verdict = audit_session(session_row())
        assert verdict is not None and verdict.short_id == "9FDF"


class TestReport:
    def test_counts_are_reported(self) -> None:
        rows = [
            session_row(),
            session_row(final_answer=""),
            session_row(final_answer=_MARKUP),
        ]
        report = format_report(audit_sessions(rows))
        assert "3 answer-bearing session(s): 1 usable, 2 unusable" in report

    def test_failure_reasons_are_shown(self) -> None:
        report = format_report(audit_sessions([session_row(final_answer="")]))
        assert "FAIL" in report and "answer is empty" in report

    def test_quiet_mode_hides_passing_sessions(self) -> None:
        rows = [session_row(task="a passing task"), session_row(final_answer="")]
        report = format_report(audit_sessions(rows), quiet=True)
        assert "a passing task" not in report
        assert "answer is empty" in report

    def test_long_tasks_are_truncated(self) -> None:
        report = format_report(audit_sessions([session_row(task="x" * 200)]))
        assert "..." in report
        assert "x" * 200 not in report

    def test_empty_database_reports_zero(self) -> None:
        assert "0 answer-bearing session(s): 0 usable, 0 unusable" in format_report([])
