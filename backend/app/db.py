"""Database connectivity: a shared connection pool, and the LangGraph
checkpointer built on top of it (ADR-014).

Cached singletons via @lru_cache, same pattern as app.config.get_settings --
built once per process, overridden in tests via FastAPI's
dependency_overrides rather than reached into and mutated.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings
from app.graph.serde import GRAPH_SERDE


@lru_cache
def get_db_pool() -> ConnectionPool:
    settings = get_settings()
    pool = ConnectionPool(
        conninfo=settings.database_url,
        max_size=5,
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=True,
    )
    return pool


@lru_cache
def get_checkpointer() -> PostgresSaver:
    """The graph's persistence layer -- what makes `interrupt()` survive
    across two separate HTTP requests (ADR-014). `.setup()` is idempotent
    (CREATE TABLE IF NOT EXISTS internally, verified directly), so calling
    it on every process start is safe and keeps the checkpoint tables
    self-provisioning rather than needing a separate manual step.
    """
    saver = PostgresSaver(conn=get_db_pool(), serde=GRAPH_SERDE)
    saver.setup()
    return saver
