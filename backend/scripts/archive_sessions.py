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
from app.db import DbPool, create_db_pool

_FIXTURE_MARKERS = ("qa_", "p2_verify_", "interview_")
_FIXTURE_EXACT_TASKS = {"do something"}


def archive_reason(session: dict[str, Any]) -> str | None:
    """Why `session` should be archived, or None to leave it alone. Ignores
    `archived_at` -- callers filter already-archived sessions themselves.

    Classifies on `title`, not `task` (WP5, ADR-036): `restart_session`
    overwrites `task` on every follow-up turn (ADR-033), so a genuine
    session that later receives a QA-styled follow-up message must not
    suddenly look like a fixture. `title` is set once, from the first
    message, and stays stable -- for any session not yet on its second
    turn the two are identical anyway, so this falls back to `task` when
    `title` is absent (a plain dict built without one, or a session whose
    'created' row has neither set yet)."""
    identifying_text = (session.get("title") or session["task"]).strip()
    if not identifying_text:
        return "untitled (no task was ever set)"
    lowered = identifying_text.lower()
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


def apply_archival(pool: DbPool, plan: list[tuple[dict[str, Any], str]]) -> int:
    """Applies an archive plan for real -- the write half of `main()` (WP3,
    Sprint 04), split out so it's directly callable, and testable against a
    real database, without argparse or pool setup. Returns how many
    sessions were archived."""
    for session, _reason in plan:
        repo.archive_session(pool, session["id"])
    return len(plan)


def restore_all(pool: DbPool) -> list[dict[str, Any]]:
    """Restores every currently-archived session -- the write half of
    `--restore-all` (WP3, Sprint 04), split out for the same reason as
    `apply_archival`. Returns the sessions that were restored."""
    sessions = repo.list_sessions_for_maintenance(pool)
    archived = [session for session in sessions if session["archived_at"] is not None]
    for session in archived:
        repo.restore_session(pool, session["id"])
    return archived


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
        if args.restore_all:
            restored = restore_all(pool)
            if not restored:
                print("No archived sessions to restore.")
                return
            for session in restored:
                print(f"restored {session['id']}")
            print(f"Restored {len(restored)} session(s).")
            return

        sessions = repo.list_sessions_for_maintenance(pool)
        plan = plan_archival(sessions)
        _print_plan(plan)
        if not args.apply:
            print("\nDry run only -- pass --apply to archive these sessions for real.")
            return

        archived_count = apply_archival(pool, plan)
        print(f"\nArchived {archived_count} session(s).")
    finally:
        pool.close()


if __name__ == "__main__":
    main()
