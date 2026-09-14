"""Pure classification tests for scripts/archive_sessions.py -- no database
needed, since archive_reason/plan_archival take plain dicts and do no I/O."""

from __future__ import annotations

import datetime
import uuid

from scripts.archive_sessions import archive_reason, plan_archival


def _session(*, task: str, archived_at=None, status: str = "done") -> dict:
    return {"id": uuid.uuid4(), "task": task, "status": status, "archived_at": archived_at}


def test_blank_task_is_archived_as_untitled() -> None:
    assert archive_reason(_session(task="")) == "untitled (no task was ever set)"


def test_whitespace_only_task_is_archived_as_untitled() -> None:
    assert archive_reason(_session(task="   ")) == "untitled (no task was ever set)"


def test_do_something_is_archived_as_smoke_test() -> None:
    assert archive_reason(_session(task="do something")) == "smoke-test placeholder task"


def test_do_something_match_is_case_insensitive() -> None:
    assert archive_reason(_session(task="Do Something")) is not None


def test_qa_prefixed_task_is_a_qa_fixture() -> None:
    reason = archive_reason(_session(task="qa_recheck_20260906: write a note"))
    assert reason == "QA fixture (task contains 'qa_')"


def test_deep_qa_prefixed_task_matches_the_qa_marker() -> None:
    assert archive_reason(_session(task="deep_qa_race_20260830: do a thing")) is not None


def test_p2_verify_prefixed_task_is_a_fixture() -> None:
    reason = archive_reason(_session(task="Use notes_store to write p2_verify_write_20260911"))
    assert reason == "QA fixture (task contains 'p2_verify_')"


def test_interview_prefixed_task_is_a_fixture() -> None:
    reason = archive_reason(_session(task="Use notes_store to write interview_reject_20260911"))
    assert reason == "QA fixture (task contains 'interview_')"


def test_genuine_task_is_left_alone() -> None:
    assert archive_reason(_session(task="Use the calculator tool to compute 47 * 89.")) is None


def test_stuck_running_session_with_no_marker_is_left_to_the_reaper() -> None:
    assert archive_reason(_session(task="to be deleted", status="running")) is None


def test_plan_archival_skips_already_archived_sessions() -> None:
    archived = _session(task="do something", archived_at=datetime.datetime.now())
    plan = plan_archival([archived])
    assert plan == []


def test_plan_archival_returns_session_and_reason_pairs() -> None:
    genuine = _session(task="Use the calculator tool to compute 47 * 89.")
    fixture = _session(task="qa_recheck_20260906: write a note")
    plan = plan_archival([genuine, fixture])
    assert [session["id"] for session, _reason in plan] == [fixture["id"]]
