"""Grade every session already in the database against the usable-answer rules.

This is the backfill half of the answer-quality work. `app/answer_quality.py`
stops *new* bad answers at `finalize`; this script says how many *old* ones are
sitting in production, and is the thing to re-run after each remediation phase
to watch the number fall.

It deliberately shares `validate_answer` with the runtime guard rather than
re-stating the rules. The bug this whole effort exists to fix was an assertion
that disagreed with the product (`status == "done"` while the answer was raw
tool-call markup); a second, drifting copy of the rules here would reintroduce
exactly that class of mistake.

Usage::

    python -m scripts.audit_sessions              # audit, print a report
    python -m scripts.audit_sessions --limit 200  # widen the window
    python -m scripts.audit_sessions --quiet      # only print failures

Exits non-zero when any terminal session carries an unusable answer, so it can
gate a deploy the same way `release_check` does.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from typing import Any

from app.answer_quality import validate_answer
from app.config import Settings
from app.db import create_db_pool
from app.repository import list_sessions

logger = logging.getLogger("agent_ops.audit_sessions")

# Statuses that are supposed to carry a user-facing answer. `created` has
# never run, `running` and `awaiting_approval` are mid-flight, and `failed`
# carries a deliberate operator-facing explanation rather than a model answer.
ANSWER_BEARING_STATUSES = frozenset({"done", "degraded"})


@dataclass(frozen=True)
class SessionVerdict:
    session_id: str
    status: str
    task: str
    reason: str | None

    @property
    def ok(self) -> bool:
        return self.reason is None

    @property
    def short_id(self) -> str:
        return self.session_id[-4:].upper()


def audit_session(session: dict[str, Any]) -> SessionVerdict | None:
    """Grade one session row, or return `None` if it isn't answer-bearing."""
    status = str(session.get("status", ""))
    if status not in ANSWER_BEARING_STATUSES:
        return None
    return SessionVerdict(
        session_id=str(session.get("id", "")),
        status=status,
        task=str(session.get("task", "")),
        reason=validate_answer(session.get("final_answer")),
    )


def audit_sessions(sessions: list[dict[str, Any]]) -> list[SessionVerdict]:
    verdicts = (audit_session(session) for session in sessions)
    return [verdict for verdict in verdicts if verdict is not None]


def format_report(verdicts: list[SessionVerdict], *, quiet: bool = False) -> str:
    """Render the verdicts as a plain-text report.

    Kept separate from I/O so the formatting is testable without a database.
    """
    failures = [v for v in verdicts if not v.ok]
    lines: list[str] = []

    shown = failures if quiet else verdicts
    for verdict in shown:
        mark = "PASS" if verdict.ok else "FAIL"
        task = verdict.task.strip().replace("\n", " ") or "(no task)"
        if len(task) > 68:
            task = f"{task[:65]}..."
        lines.append(f"  [{mark}] {verdict.short_id}  {verdict.status:<9} {task}")
        if not verdict.ok:
            lines.append(f"         -> {verdict.reason}")

    lines.append("")
    lines.append(
        f"  {len(verdicts)} answer-bearing session(s): "
        f"{len(verdicts) - len(failures)} usable, {len(failures)} unusable"
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="how many sessions to audit")
    parser.add_argument("--quiet", action="store_true", help="print only failing sessions")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    pool = create_db_pool(Settings())
    try:
        pool.open(wait=True, timeout=10)
        sessions = list_sessions(pool, limit=args.limit)
    finally:
        pool.close()

    verdicts = audit_sessions(sessions)
    print(format_report(verdicts, quiet=args.quiet))

    if any(not verdict.ok for verdict in verdicts):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
