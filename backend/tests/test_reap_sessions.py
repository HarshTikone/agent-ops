"""Tests for scripts/reap_sessions.py: pure classification (no database
needed, since reap_action/plan_reap take plain dicts and a fixed `now`),
plus DB-backed coverage (WP3, Sprint 04) for apply_reap -- the write path
the pure tests above can't reach."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app import repository as repo
from scripts import reap_sessions
from scripts.reap_sessions import (
    _INTERRUPTED_MESSAGE,
    CREATED_STALE_AFTER,
    RUNNING_STALE_AFTER,
    apply_reap,
    plan_reap,
    reap_action,
)

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


# --- DB-backed: the write path (WP3, Sprint 04) -------------------------


def _backdate(db_pool, session_id, *, column: str, to) -> None:
    # `column` is always a literal ("updated_at"/"created_at") from a call
    # site in this file, never external input.
    with db_pool.connection() as conn:
        conn.execute(f"UPDATE sessions SET {column} = %s WHERE id = %s", (to, session_id))


def test_apply_reap_fails_a_stale_running_session(db_pool) -> None:
    session = repo.create_session(db_pool, task="stale running task")
    session_id = session["id"]
    stale = datetime.now(UTC) - RUNNING_STALE_AFTER - timedelta(minutes=1)
    _backdate(db_pool, session_id, column="updated_at", to=stale)
    try:
        target = next(
            s for s in repo.list_sessions_for_maintenance(db_pool) if s["id"] == session_id
        )
        plan = plan_reap([target], now=datetime.now(UTC))
        assert len(plan) == 1

        applied = apply_reap(db_pool, plan)

        assert applied == 1
        final = repo.get_session(db_pool, session_id)
        assert final["status"] == "failed"
        assert final["final_answer"] == _INTERRUPTED_MESSAGE
        events = repo.list_trace_events(db_pool, session_id)
        reaped = [e for e in events if e["node"] == "system" and "REAPED" in e["detail"]]
        assert len(reaped) == 1
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))


def test_apply_reap_archives_a_stale_created_session(db_pool) -> None:
    session = repo.create_session(db_pool)  # blank task -> 'created'
    session_id = session["id"]
    stale = datetime.now(UTC) - CREATED_STALE_AFTER - timedelta(hours=1)
    _backdate(db_pool, session_id, column="created_at", to=stale)
    try:
        target = next(
            s for s in repo.list_sessions_for_maintenance(db_pool) if s["id"] == session_id
        )
        plan = plan_reap([target], now=datetime.now(UTC))
        assert len(plan) == 1

        applied = apply_reap(db_pool, plan)

        assert applied == 1
        final = repo.get_session(db_pool, session_id)
        assert final["archived_at"] is not None
        assert final["status"] == "created"  # archived, not failed -- it never ran
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))


def test_apply_reap_skips_a_session_that_changed_since_being_read(db_pool) -> None:
    """WP2/ADR-035's compare-and-swap, exercised through the script's own
    apply path this time, not the repository function directly."""
    session = repo.create_session(db_pool, task="stale running task")
    session_id = session["id"]
    stale = datetime.now(UTC) - RUNNING_STALE_AFTER - timedelta(minutes=1)
    _backdate(db_pool, session_id, column="updated_at", to=stale)
    try:
        target = next(
            s for s in repo.list_sessions_for_maintenance(db_pool) if s["id"] == session_id
        )
        plan = plan_reap([target], now=datetime.now(UTC))

        # The run finishes for real between the read above and apply_reap below.
        repo.update_session_status(
            db_pool, session_id, status="done", final_answer="finished first"
        )

        applied = apply_reap(db_pool, plan)

        assert applied == 0
        final = repo.get_session(db_pool, session_id)
        assert final["status"] == "done"
        assert final["final_answer"] == "finished first"
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))


def test_main_dry_run_writes_nothing(db_pool, monkeypatch, capsys) -> None:
    """CLI flag wiring smoke test: with no --apply, main() must print a plan
    and leave the database untouched."""
    session = repo.create_session(db_pool, task="not stale yet")
    session_id = session["id"]
    try:
        monkeypatch.setattr("sys.argv", ["reap_sessions"])
        reap_sessions.main()

        output = capsys.readouterr().out
        assert "Dry run only" in output or "Nothing to reap" in output
        final = repo.get_session(db_pool, session_id)
        assert final["status"] == "running"
        assert final["archived_at"] is None
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))


def test_main_apply_reaps_for_real(db_pool, monkeypatch, capsys) -> None:
    session = repo.create_session(db_pool, task="stale running task")
    session_id = session["id"]
    stale = datetime.now(UTC) - RUNNING_STALE_AFTER - timedelta(minutes=1)
    _backdate(db_pool, session_id, column="updated_at", to=stale)
    try:
        monkeypatch.setattr("sys.argv", ["reap_sessions", "--apply"])
        reap_sessions.main()

        output = capsys.readouterr().out
        assert "Reaped" in output
        assert repo.get_session(db_pool, session_id)["status"] == "failed"
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
