"""Database connectivity: a shared connection pool, and the LangGraph
checkpointer built on top of it (ADR-014).

The application lifespan creates and owns the pool. Request dependencies
only retrieve that application-owned resource.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import HTTPException, Request
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import Settings
from app.graph.serde import GRAPH_SERDE

DbConnection = Connection[dict[str, Any]]
DbPool = ConnectionPool[DbConnection]


def create_db_pool(settings: Settings) -> DbPool:
    pool = ConnectionPool(
        conninfo=settings.database_url,
        max_size=5,
        kwargs={"autocommit": True, "row_factory": dict_row},
        check=ConnectionPool.check_connection,
        open=False,
    )
    return cast(DbPool, pool)


def get_db_pool(request: Request) -> DbPool:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="database is not available")
    return cast(DbPool, pool)


def get_optional_db_pool(request: Request) -> DbPool | None:
    return cast(DbPool | None, getattr(request.app.state, "db_pool", None))


def create_checkpointer(pool: DbPool) -> PostgresSaver:
    """The graph's persistence layer -- what makes `interrupt()` survive
    across two separate HTTP requests (ADR-014). `.setup()` is idempotent
    (CREATE TABLE IF NOT EXISTS internally, verified directly), so calling
    it on every process start is safe and keeps the checkpoint tables
    self-provisioning rather than needing a separate manual step.
    """
    saver = PostgresSaver(conn=pool, serde=GRAPH_SERDE)
    saver.setup()
    return saver


def get_checkpointer(request: Request) -> PostgresSaver:
    saver = getattr(request.app.state, "checkpointer", None)
    if saver is None:
        saver = create_checkpointer(get_db_pool(request))
        request.app.state.checkpointer = saver
    return cast(PostgresSaver, saver)
