"""Postgres access layer for the API service.

A single ``AsyncConnectionPool`` lives on ``app.state.db_pool`` for the
lifetime of the FastAPI process. Chat history (:mod:`api.agent.history`)
and the station-name resolver (:mod:`api.stations`) acquire connections
from it. Live network state is read from the TfL Unified API
(:mod:`api.live`), not from SQL — the ``raw.*`` warehouse was removed in
ADR 014.
"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool


def build_pool(dsn: str) -> AsyncConnectionPool:
    """Build the API process-wide connection pool.

    The pool is constructed with ``open=False``; callers (the FastAPI
    lifespan) must ``await pool.open()`` before serving requests.

    Args:
        dsn: libpq-compatible connection string (``DATABASE_URL``).

    Returns:
        Configured but unopened ``AsyncConnectionPool``.
    """
    return AsyncConnectionPool(dsn, min_size=1, max_size=4, open=False)
