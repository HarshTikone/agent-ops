"""Health and readiness endpoints.

Split into two deliberately different checks:

- `/health` — liveness. Answers "is the process up and able to respond at
  all?" Always returns 200 if the app is running; used by Render/uptime
  monitors that just need a fast, dependency-free ping.
- `/health/ready` — readiness. Answers "is this instance actually able to
  serve a real request?" Reports whether the required provider/database
  configuration is present, without ever returning a secret value. This is
  the one that should fail loudly in a demo if, say, GEMINI_API_KEY was
  never set on the deploy target — a genuinely observed failure mode
  (missing config) rather than a silent 500 three requests later.

`/health/ready`'s three-way status (see ADR-009) is deliberate: Gemini +
Supabase + database are hard requirements — without any one of them the
planner literally cannot do anything (no LLM at all, or nowhere to persist
a session/trace/approval). OpenRouter is a resilience add-on per ADR-002:
the failover only fires on Gemini timeout/5xx/rate-limit, never on a missing
key or auth failure (that's deliberately not caught, so a real config bug
doesn't masquerade as "provider failed over cleanly") — so an OpenRouter-only
setup with no Gemini key cannot actually serve anything either, and a
Gemini-only setup with no OpenRouter key can serve everything, just with no
safety net if Gemini has an outage mid-demo.
"""

import psycopg
from fastapi import APIRouter, Depends
from psycopg_pool import PoolTimeout

from app.config import Settings, get_settings
from app.db import DbPool, get_optional_db_pool

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


def _database_reachable(pool: DbPool | None, timeout_seconds: float) -> bool:
    if pool is None:
        return False
    try:
        with pool.connection(timeout=timeout_seconds) as connection, connection.transaction():
            connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(round(timeout_seconds * 1_000)),),
            )
            connection.execute("SELECT 1").fetchone()
        return True
    except (PoolTimeout, psycopg.Error):
        return False


@router.get("/health/ready")
def readiness(
    settings: Settings = Depends(get_settings),
    pool: DbPool | None = Depends(get_optional_db_pool),
) -> dict[str, object]:
    database_reachable = _database_reachable(pool, settings.readiness_timeout_seconds)
    checks = {
        "gemini_api_key_set": bool(settings.gemini_api_key),
        "openrouter_api_key_set": bool(settings.openrouter_api_key),
        "supabase_configured": bool(settings.supabase_url and settings.supabase_secret_key),
        "database_configured": bool(settings.database_url),
        "database_reachable": database_reachable,
    }

    can_serve = (
        settings.llm_providers_configured
        and checks["supabase_configured"]
        and checks["database_configured"]
        and checks["database_reachable"]
    )

    if not can_serve:
        status = "not_ready"
    elif not checks["openrouter_api_key_set"]:
        status = "degraded"
    else:
        status = "ready"

    return {"status": status, "checks": checks}
