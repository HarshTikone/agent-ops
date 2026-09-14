"""Archive QA/demo-fixture sessions that were never meant to stay on the
production session list -- soft-archives them via `archived_at` rather than
deleting rows, so an archived session still opens by its direct URL and the
whole batch can be undone with --restore-all if the judgment call was wrong.

Classification is pure and separate from I/O (`archive_reason`/`plan_archival`
below take plain dicts and do no I/O) so it can be tested without a database
and read without tracing through argument parsing and connection handling.

Matches the naming conventions this project's own QA process has used for
throwaway sessions: `qa_*` / `deep_qa_*` (both contain "qa_"), `p2_verify_*`,
`interview_*`, a session that never got a task at all (blank), and the
literal "do something" smoke-test task. Anything else is left alone.

Dry run by default -- prints the plan and touches nothing.

Usage (from backend/):
    python -m scripts.archive_sessions               # dry run, prints the plan
    python -m scripts.archive_sessions --apply        # archive for real
    python -m scripts.archive_sessions --restore-all  # undo every archive
"""

from __future__ import annotations

import argparse
from typing import Any

from app import repository as repo
from app.config import get_settings
from app.db import create_db_pool

_FIXTURE_MARKERS = ("qa_", "p2_verify_", "interview_")
_FIXTURE_EXACT_TASKS = {"do something"}


def archive_reason(session: dict[str, Any]) -> str | None:
    """Why `session` should be archived, or None to leave it alone. Ignores
    `archived_at` -- callers filter already-archived sessions themselves."""
    task = session["task"].strip()
    if not task:
        return "untitled (no task was ever set)"
    lowered = task.lower()
    for marker in _FIXTURE_MARKERS:
        if marker in lowered:
            return f"QA fixture (task contains '{marker}')"
    if lowered in _FIXTURE_EXACT_TASKS:
        return "smoke-test placeholder task"
    return None


def plan_archival(sessions: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    """Sessions not already archived, paired with why each would be archived."""
    plan = []
    for session in sessions:
        if session["archived_at"] is not None:
            continue
        reason = archive_reason(session)
        if reason is not None:
            plan.append((session, reason))
    return plan


def _print_plan(plan: list[tuple[dict[str, Any], str]]) -> None:
    if not plan:
        print("Nothing to archive.")
        return
    print(f"{len(plan)} session(s) would be archived:")
    for session, reason in plan:
        print(
            f"  {session['id']}  [{session['status']:>17}]  {reason:<38}  {session['task'][:60]!r}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="archive the planned sessions for real"
    )
    parser.add_argument(
        "--restore-all", action="store_true", help="restore every currently archived session"
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set -- nothing to archive against.")

    pool = create_db_pool(settings)
    pool.open(wait=True, timeout=10)
    try:
        sessions = repo.list_sessions_for_maintenance(pool)

        if args.restore_all:
            archived = [session for session in sessions if session["archived_at"] is not None]
            if not archived:
                print("No archived sessions to restore.")
                return
            for session in archived:
                repo.restore_session(pool, session["id"])
                print(f"restored {session['id']}")
            print(f"Restored {len(archived)} session(s).")
            return

        plan = plan_archival(sessions)
        _print_plan(plan)
        if not args.apply:
            print("\nDry run only -- pass --apply to archive these sessions for real.")
            return

        for session, _reason in plan:
            repo.archive_session(pool, session["id"])
        print(f"\nArchived {len(plan)} session(s).")
    finally:
        pool.close()


if __name__ == "__main__":
    main()
