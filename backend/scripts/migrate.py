"""Apply SQL migrations in backend/migrations/ that haven't run yet.

Deliberately manual (run by a developer, or a one-time deploy step Day 6
wires up) rather than auto-run on every app boot -- auto-migrating on
startup is a common footgun with concurrent workers all racing to migrate
at once, and this project's scale doesn't need it. Idempotent: safe to
re-run, tracks applied migrations in schema_migrations.

Usage (from backend/): python -m scripts.migrate
Reads DATABASE_URL the same way the app does -- via app.config.get_settings,
so this always targets the same database the app itself would connect to.
"""

from pathlib import Path

import psycopg

from app.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MIGRATION_LOCK_ID = 1_946_795_992


def apply_migrations(
    conn: psycopg.Connection[tuple[object, ...]], migration_files: list[Path]
) -> None:
    """Apply pending files while holding one session-level migration lock."""
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """)
        conn.commit()

        applied = {
            row[0] for row in conn.execute("SELECT filename FROM schema_migrations").fetchall()
        }

        for path in migration_files:
            if path.name in applied:
                print(f"skip  {path.name} (already applied)")
                continue
            sql = path.read_text(encoding="utf-8")
            with conn.transaction():
                conn.execute(sql)
                conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
            print(f"apply {path.name}")
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))


def main() -> None:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set -- nothing to migrate against.")

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print(f"No migration files found in {MIGRATIONS_DIR}")
        return

    with psycopg.connect(settings.database_url) as conn:
        apply_migrations(conn, migration_files)


if __name__ == "__main__":
    main()
