"""Pure classification tests for scripts/reap_sessions.py -- no database
needed, since reap_action/plan_reap take plain dicts and a fixed `now`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from scripts.reap_sessions import CREATED_STALE_AFTER, RUNNING_STALE_AFTER, plan_reap, reap_action

_NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)


def _session(
    *,
    status: str,
    created_at: datetime = _NOW,
    updated_at: datetime = _NOW,
    archived_at: datetime | None = None,
    task: str = "some task",
) -> dict:
    return {
        "id": uuid.uuid4(),
        "task": task,
        "status": status,
        "archived_at": archived_at,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def test_running_session_just_started_is_left_alone() -> None:
    session = _session(status="running", updated_at=_NOW - timedelta(minutes=1))
    assert reap_action(session, now=_NOW) is None


def test_running_session_stalled_past_threshold_is_failed() -> None:
    session = _session(status="running", updated_at=_NOW - RUNNING_STALE_AFTER)
    action, reason = reap_action(session, now=_NOW)
    assert action == "fail"
    assert "running" in reason


def test_running_session_just_under_threshold_is_left_alone() -> None:
    session = _session(
        status="running", updated_at=_NOW - RUNNING_STALE_AFTER + timedelta(seconds=1)
    )
    assert reap_action(session, now=_NOW) is None


def test_created_session_from_today_is_left_alone() -> None:
    session = _session(status="created", created_at=_NOW - timedelta(hours=1), task="")
    assert reap_action(session, now=_NOW) is None


def test_created_session_over_a_day_old_is_archived() -> None:
    session = _session(status="created", created_at=_NOW - CREATED_STALE_AFTER, task="")
    action, reason = reap_action(session, now=_NOW)
    assert action == "archive"
    assert "never messaged" in reason


def test_awaiting_approval_is_never_touched_no_matter_how_old() -> None:
    session = _session(
        status="awaiting_approval",
        created_at=_NOW - timedelta(days=365),
        updated_at=_NOW - timedelta(days=365),
    )
    assert reap_action(session, now=_NOW) is None


def test_done_and_failed_sessions_are_left_alone() -> None:
    for status in ("done", "failed", "degraded"):
        session = _session(
            status=status,
            created_at=_NOW - timedelta(days=365),
            updated_at=_NOW - timedelta(days=365),
        )
        assert reap_action(session, now=_NOW) is None


def test_already_archived_session_is_never_reaped_again() -> None:
    session = _session(
        status="running",
        updated_at=_NOW - timedelta(days=1),
        archived_at=_NOW - timedelta(hours=1),
    )
    assert reap_action(session, now=_NOW) is None


def test_plan_reap_returns_only_actionable_sessions_with_reasons() -> None:
    stale_running = _session(status="running", updated_at=_NOW - timedelta(hours=1))
    fresh_running = _session(status="running", updated_at=_NOW - timedelta(seconds=5))
    stale_created = _session(status="created", created_at=_NOW - timedelta(days=3), task="")
    awaiting = _session(status="awaiting_approval", updated_at=_NOW - timedelta(days=10))

    plan = plan_reap([stale_running, fresh_running, stale_created, awaiting], now=_NOW)

    reaped_ids = {session["id"] for session, _action, _reason in plan}
    assert reaped_ids == {stale_running["id"], stale_created["id"]}
    actions_by_id = {session["id"]: action for session, action, _reason in plan}
    assert actions_by_id[stale_running["id"]] == "fail"
    assert actions_by_id[stale_created["id"]] == "archive"
