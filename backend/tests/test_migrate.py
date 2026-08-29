"""Migration runner locking and repeat-run behavior."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from scripts.migrate import MIGRATION_LOCK_ID, apply_migrations


class _Result:
    def __init__(self, rows: list[tuple[str]] | None = None) -> None:
        self.rows = rows or []

    def fetchall(self) -> list[tuple[str]]:
        return self.rows


class _FakeConnection:
    def __init__(self, *, applied: set[str] | None = None, fail_sql: str | None = None) -> None:
        self.applied = applied or set()
        self.fail_sql = fail_sql
        self.calls: list[tuple[str, Any]] = []
        self.commits = 0

    def execute(self, sql: str, params: Any = None) -> _Result:
        normalized = " ".join(sql.split())
        self.calls.append((normalized, params))
        if self.fail_sql and self.fail_sql in sql:
            raise RuntimeError("migration failed")
        if normalized == "SELECT filename FROM schema_migrations":
            return _Result([(name,) for name in self.applied])
        return _Result()

    def commit(self) -> None:
        self.commits += 1

    def transaction(self):
        return nullcontext()


def test_repeat_run_skips_applied_migration_while_holding_lock(tmp_path: Path) -> None:
    migration = tmp_path / "0001_test.sql"
    migration.write_text("SELECT 'must not run';", encoding="utf-8")
    conn = _FakeConnection(applied={migration.name})

    apply_migrations(conn, [migration])  # type: ignore[arg-type]

    assert conn.calls[0] == ("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
    assert conn.calls[-1] == ("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))
    assert all("must not run" not in sql for sql, _ in conn.calls)


def test_migration_lock_is_released_after_failure(tmp_path: Path) -> None:
    migration = tmp_path / "0001_test.sql"
    migration.write_text("BROKEN MIGRATION", encoding="utf-8")
    conn = _FakeConnection(fail_sql="BROKEN MIGRATION")

    with pytest.raises(RuntimeError, match="migration failed"):
        apply_migrations(conn, [migration])  # type: ignore[arg-type]

    assert conn.calls[-1] == ("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))
