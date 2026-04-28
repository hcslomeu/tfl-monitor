"""Postgres access layer for the API service.

A single ``AsyncConnectionPool`` lives on ``app.state.db_pool`` for the
lifetime of the FastAPI process. Handlers acquire a connection per
request via ``async with pool.connection() as conn``. SQL is kept here
so the route layer stays thin.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from api.schemas import LineReliabilityResponse, LineStatusResponse


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


# /status/live -- latest snapshot per line out of raw events newer than 15
# minutes. The ingested_at filter pins the planner to
# idx_line_status_ingested_at; without it the query degrades to a full scan.
LIVE_STATUS_SQL = """
SELECT DISTINCT ON (payload->>'line_id')
       payload->>'line_id'                     AS line_id,
       payload->>'line_name'                   AS line_name,
       payload->>'mode'                        AS mode,
       (payload->>'status_severity')::int      AS status_severity,
       payload->>'status_severity_description' AS status_severity_description,
       NULLIF(payload->>'reason', '')          AS reason,
       (payload->>'valid_from')::timestamptz   AS valid_from,
       (payload->>'valid_to')::timestamptz     AS valid_to
FROM raw.line_status
WHERE event_type = 'line-status.snapshot'
  AND ingested_at >= now() - INTERVAL '15 minutes'
ORDER BY payload->>'line_id', ingested_at DESC
"""


HISTORY_SQL = """
SELECT line_id, line_name, mode,
       status_severity, status_severity_description,
       reason, valid_from, valid_to
FROM analytics.stg_line_status
WHERE valid_from >= %(from)s
  AND valid_from <  %(to)s
  AND ( %(line_id)s IS NULL OR line_id = %(line_id)s )
ORDER BY valid_from ASC, line_id ASC
LIMIT 10000
"""


# /reliability aggregate. Severity 10 == "Good Service" in TfL's scale, so
# reliability_percent is the share of snapshots in that bucket. NULLIF on
# the divisor cannot fire (the WHERE clause guarantees rows), but the CASE
# keeps the SQL defensible if the predicate is ever loosened.
RELIABILITY_AGG_SQL = """
SELECT
    line_id,
    MIN(line_name) AS line_name,
    MIN(mode)      AS mode,
    SUM(snapshot_count)::int AS sample_size,
    CASE WHEN SUM(snapshot_count) = 0 THEN 0
         ELSE ROUND(
             100.0
             * SUM(snapshot_count) FILTER (WHERE status_severity = 10)
             / SUM(snapshot_count),
             1
         )::float
    END AS reliability_percent
FROM analytics.mart_tube_reliability_daily
WHERE line_id = %(line_id)s
  AND calendar_date >= (current_date - %(window)s::int)
GROUP BY line_id
"""


RELIABILITY_HISTOGRAM_SQL = """
SELECT status_severity::text AS severity,
       SUM(snapshot_count)::int AS count
FROM analytics.mart_tube_reliability_daily
WHERE line_id = %(line_id)s
  AND calendar_date >= (current_date - %(window)s::int)
GROUP BY status_severity
ORDER BY status_severity
"""


async def fetch_live_status(pool: AsyncConnectionPool) -> list[LineStatusResponse]:
    """Return the most recent snapshot per line within the freshness window."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(LIVE_STATUS_SQL)
        rows: list[dict[str, Any]] = await cur.fetchall()
    return [LineStatusResponse.model_validate(row) for row in rows]


async def fetch_status_history(
    pool: AsyncConnectionPool,
    *,
    from_dt: datetime,
    to_dt: datetime,
    line_id: str | None,
) -> list[LineStatusResponse]:
    """Return historical snapshots from the staging layer."""
    params = {"from": from_dt, "to": to_dt, "line_id": line_id}
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(HISTORY_SQL, params)
        rows: list[dict[str, Any]] = await cur.fetchall()
    return [LineStatusResponse.model_validate(row) for row in rows]


async def fetch_reliability(
    pool: AsyncConnectionPool,
    *,
    line_id: str,
    window: int,
) -> LineReliabilityResponse | None:
    """Return reliability aggregate for ``line_id`` over the last ``window`` days.

    Returns ``None`` when no snapshots exist for that line in the window.
    """
    params = {"line_id": line_id, "window": window}
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(RELIABILITY_AGG_SQL, params)
            agg = await cur.fetchone()
        if agg is None or agg["sample_size"] == 0:
            return None
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(RELIABILITY_HISTOGRAM_SQL, params)
            hist_rows: list[dict[str, Any]] = await cur.fetchall()

    histogram = {row["severity"]: int(row["count"]) for row in hist_rows if row["count"] > 0}
    return LineReliabilityResponse(
        line_id=agg["line_id"],
        line_name=agg["line_name"],
        mode=agg["mode"],
        window_days=window,
        reliability_percent=float(agg["reliability_percent"]),
        sample_size=int(agg["sample_size"]),
        severity_histogram=histogram,
    )
