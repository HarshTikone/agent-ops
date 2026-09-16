"""Reap sessions stranded outside the crash handler's reach.

Two ways a session strands: `created` and never messaged (the row exists but
`send_message` was never called), or `running` when the process died outside
`send_message`'s own `try`/`except` (a killed container, not an exception
inside the request) -- that handler can only catch failures *within* a
request it's running, not a process that vanishes mid-request.

Classification is pure and separate from I/O (`reap_action`/`plan_reap`
below take plain dicts and a fixed `now`, and do no I/O) for the same reason
as `scripts/archive_sessions.py`: testable without a database, and readable
without tracing through connection handling.

`running` older than RUNNING_STALE_AFTER (measured from `updated_at`, the
last time anything touched the row -- this app's requests are fully
synchronous, so a session sitting `running` untouched for this long did not
just get unlucky, its process died) is marked `failed` with an honest
final_answer. `created` older than CREATED_STALE_AFTER is archived, not
failed -- it never ran, so there is nothing to report as a failure.

`awaiting_approval` is never touched. That state is legitimately long-lived,
waiting on a human by design -- reaping it would silently kill a pending
approval, the worst outcome this script could cause.

Dry run by default -- prints the plan and touches nothing.

Usage (from backend/):
    python -m scripts.reap_sessions          # dry run, prints the plan
    python -m scripts.reap_sessions --apply   # reap for real
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from typing import Any

from app import repository as repo
from app.config import get_settings
from app.db import create_db_pool

RUNNING_STALE_AFTER = timedelta(minutes=15)
CREATED_STALE_AFTER = timedelta(days=1)
_INTERRUPTED_MESSAGE = "The run was interrupted before completion."


def reap_action(session: dict[str, Any], *, now: datetime) -> tuple[str, str] | None:
    """('fail', reason) for a stalled running session, ('archive', reason)
    for a stale never-messaged one, or None to leave `session` alone.
    Ignores already-archived sessions -- callers filter those themselves."""
    if session["archived_at"] is not None:
        return None
    status = session["status"]
    if status == "running":
        stalled_for = now - session["updated_at"]
        if stalled_for >= RUNNING_STALE_AFTER:
            return "fail", f"running with no update for {stalled_for}"
        return None
    if status == "created":
        age = now - session["created_at"]
        if age >= CREATED_STALE_AFTER:
            return "archive", f"created {age} ago and never messaged"
        return None
    return None


def plan_reap(
    sessions: list[dict[str, Any]], *, now: datetime
) -> list[tuple[dict[str, Any], str, str]]:
    """Sessions to reap, paired with the action ('fail' or 'archive') and why."""
    plan = []
    for session in sessions:
        result = reap_action(session, now=now)
        if result is not None:
            action, reason = result
            plan.append((session, action, reason))
    return plan


def _print_plan(plan: list[tuple[dict[str, Any], str, str]]) -> None:
    if not plan:
        print("Nothing to reap.")
        return
    print(f"{len(plan)} session(s) would be reaped:")
    for session, action, reason in plan:
        print(f"  {session['id']}  {action:<8}  {reason:<40}  {session['task'][:40]!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="reap the planned sessions for real")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set -- nothing to reap against.")

    pool = create_db_pool(settings)
    pool.open(wait=True, timeout=10)
    try:
        sessions = repo.list_sessions_for_maintenance(pool)
        plan = plan_reap(sessions, now=datetime.now(UTC))
        _print_plan(plan)
        if not args.apply:
            print("\nDry run only -- pass --apply to reap these sessions for real.")
            return

        for session, action, reason in plan:
            if action == "fail":
                repo.add_trace_event(pool, session["id"], node="system", detail=f"REAPED: {reason}")
                repo.update_session_status(
                    pool, session["id"], status="failed", final_answer=_INTERRUPTED_MESSAGE
                )
            else:
                repo.archive_session(pool, session["id"])
        print(f"\nReaped {len(plan)} session(s).")
    finally:
        pool.close()


if __name__ == "__main__":
    main()
