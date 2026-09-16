"""Tests for scripts/archive_sessions.py: pure classification (no database
needed, since archive_reason/plan_archival take plain dicts and do no I/O),
plus DB-backed coverage (WP3, Sprint 04) for the write paths -- apply_archival
and restore_all -- that the pure tests above can't reach."""

from __future__ import annotations

import datetime
import uuid

from app import repository as repo
from scripts import archive_sessions
from scripts.archive_sessions import apply_archival, archive_reason, plan_archival, restore_all


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


# --- DB-backed: the write paths (WP3, Sprint 04) -----------------------


def test_apply_archival_archives_only_the_planned_sessions(db_pool) -> None:
    genuine = repo.create_session(db_pool, task="Use the calculator tool to compute 47 * 89.")
    fixture = repo.create_session(db_pool, task="qa_recheck_20260906: write a note")
    try:
        sessions = repo.list_sessions_for_maintenance(db_pool)
        plan = plan_archival([s for s in sessions if s["id"] in (genuine["id"], fixture["id"])])

        archived_count = apply_archival(db_pool, plan)

        assert archived_count == 1
        assert repo.get_session(db_pool, fixture["id"])["archived_at"] is not None
        assert repo.get_session(db_pool, genuine["id"])["archived_at"] is None
    finally:
        with db_pool.connection() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE id IN (%s, %s)", (genuine["id"], fixture["id"])
            )


def test_restore_all_restores_every_archived_session(db_pool) -> None:
    archived_one = repo.create_session(db_pool, task="qa_a: fixture one")
    archived_two = repo.create_session(db_pool, task="qa_b: fixture two")
    untouched = repo.create_session(db_pool, task="a genuine session")
    repo.archive_session(db_pool, archived_one["id"])
    repo.archive_session(db_pool, archived_two["id"])
    try:
        restored = restore_all(db_pool)
        restored_ids = {s["id"] for s in restored}

        assert archived_one["id"] in restored_ids
        assert archived_two["id"] in restored_ids
        assert untouched["id"] not in restored_ids
        assert repo.get_session(db_pool, archived_one["id"])["archived_at"] is None
        assert repo.get_session(db_pool, archived_two["id"])["archived_at"] is None
        # was never archived -- restoring is idempotent, but confirm it's
        # not what made this session's archived_at None.
        assert repo.get_session(db_pool, untouched["id"])["archived_at"] is None
    finally:
        with db_pool.connection() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE id IN (%s, %s, %s)",
                (archived_one["id"], archived_two["id"], untouched["id"]),
            )


def test_restore_all_returns_an_empty_list_when_nothing_is_archived(db_pool) -> None:
    session = repo.create_session(db_pool, task="a genuine session")
    try:
        restored = restore_all(db_pool)
        assert session["id"] not in {s["id"] for s in restored}
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session["id"],))


def test_main_dry_run_writes_nothing(db_pool, monkeypatch, capsys) -> None:
    """CLI flag wiring smoke test: with no --apply, main() must print a plan
    and leave the database untouched."""
    fixture = repo.create_session(db_pool, task="qa_dry_run_smoke: should not be touched")
    try:
        monkeypatch.setattr("sys.argv", ["archive_sessions"])
        archive_sessions.main()

        output = capsys.readouterr().out
        assert "Dry run only" in output
        assert repo.get_session(db_pool, fixture["id"])["archived_at"] is None
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (fixture["id"],))


def test_main_apply_archives_for_real(db_pool, monkeypatch, capsys) -> None:
    fixture = repo.create_session(db_pool, task="qa_apply_smoke: should be archived")
    try:
        monkeypatch.setattr("sys.argv", ["archive_sessions", "--apply"])
        archive_sessions.main()

        output = capsys.readouterr().out
        assert "Archived" in output
        assert repo.get_session(db_pool, fixture["id"])["archived_at"] is not None
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (fixture["id"],))
