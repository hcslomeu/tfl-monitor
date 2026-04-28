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

from api.schemas import (
    BusPunctualityResponse,
    DisruptionResponse,
    LineReliabilityResponse,
    LineStatusResponse,
    Mode,
)

# Bus punctuality is reported over a fixed 7-day window. The OpenAPI
# contract does not declare a ``window`` query parameter, and the
# example payload uses 7. Hard-coded here to keep the handler signature
# small.
BUS_PUNCTUALITY_WINDOW_DAYS = 7


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
# Window semantics: ``window=N`` covers the last N calendar days (UTC),
# inclusive of today. ``current_date - (window - 1)`` keeps the bound
# closed at the start of the window so ``window=1`` returns only today.
# COALESCE guards reliability_percent against NULL when the window
# contains snapshots but none at severity 10 (line in degraded service).
RELIABILITY_AGG_SQL = """
SELECT
    line_id,
    MIN(line_name) AS line_name,
    MIN(mode)      AS mode,
    SUM(snapshot_count)::int AS sample_size,
    COALESCE(
        ROUND(
            100.0
            * SUM(snapshot_count) FILTER (WHERE status_severity = 10)
            / NULLIF(SUM(snapshot_count), 0),
            1
        ),
        0
    )::float AS reliability_percent
FROM analytics.mart_tube_reliability_daily
WHERE line_id = %(line_id)s
  AND calendar_date >= (current_date - (%(window)s::int - 1))
GROUP BY line_id
"""


RELIABILITY_HISTOGRAM_SQL = """
SELECT status_severity::text AS severity,
       SUM(snapshot_count)::int AS count
FROM analytics.mart_tube_reliability_daily
WHERE line_id = %(line_id)s
  AND calendar_date >= (current_date - (%(window)s::int - 1))
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
        if agg is None or not agg.get("sample_size"):
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


# /disruptions/recent -- snapshot-grain pull from stg_disruptions; the
# daily mart drops description/summary/affected_stops/closure_text/
# created/last_update which the OpenAPI contract requires. ``mode``
# filtering goes through stg_line_status because ref.lines is empty
# until TM-A2/TM-A3. The triple-keyed ``%(mode)s`` bind expands at
# every call site (psycopg substitutes named parameters by name, so a
# single bound value drives the OR short-circuit, the EXISTS predicate,
# and any future filter site identically).
DISRUPTIONS_SQL = """
SELECT
    disruption_id,
    category,
    category_description,
    description,
    summary,
    COALESCE(closure_text, '')                AS closure_text,
    severity,
    created,
    last_update,
    affected_routes,
    affected_stops
FROM analytics.stg_disruptions sd
WHERE event_type = 'disruptions.snapshot'
  AND (
      %(mode)s IS NULL
      OR EXISTS (
          SELECT 1
          FROM analytics.stg_line_status sls
          WHERE sls.mode = %(mode)s
            AND sls.line_id IN (
                SELECT jsonb_array_elements_text(sd.affected_routes)
            )
      )
  )
ORDER BY last_update DESC NULLS LAST, ingested_at DESC
LIMIT %(limit)s
"""


# /bus/{stop_id}/punctuality -- a documented PROXY computed on top of
# stg_arrivals.time_to_station_seconds. TfL publishes arrival
# predictions (not actual departure events), so the percentages
# reflect the distribution of predictions, not realised arrivals. The
# 300 s threshold matches TfL's own published 5-minute bus performance
# KPI (TfL Annual Report 2023/24); using the same threshold keeps the
# proxy aligned with the public KPI even though the underlying signal
# is different. Buckets:
#   late    -- time_to_station_seconds < 0       -- predicted arrival
#                                                   already past
#   on_time -- 0 <= time_to_station_seconds <= 300 -- bus visible in
#                                                     a 5-minute window
#   early   -- time_to_station_seconds > 300      -- prediction shows
#                                                    bus more than 5
#                                                    minutes out
BUS_PUNCTUALITY_SQL = """
SELECT
    COUNT(*)::int AS sample_size,
    COUNT(*) FILTER (WHERE time_to_station_seconds < 0)::int AS late_count,
    COUNT(*) FILTER (
        WHERE time_to_station_seconds BETWEEN 0 AND 300
    )::int AS on_time_count,
    COUNT(*) FILTER (WHERE time_to_station_seconds > 300)::int AS early_count
FROM analytics.stg_arrivals
WHERE station_id = %(stop_id)s
  AND ingested_at >= now() - (%(window)s::int * INTERVAL '1 day')
"""


# Fetch the most recently observed station_name for a stop. The bus
# mart does not denormalise station_name; stg_arrivals does. One
# extra round-trip on the same connection (mirrors the two-query
# pattern used by /reliability).
BUS_STOP_NAME_SQL = """
SELECT station_name
FROM analytics.stg_arrivals
WHERE station_id = %(stop_id)s
ORDER BY ingested_at DESC
LIMIT 1
"""


def _as_str_list(value: Any) -> list[str]:
    """Coerce a JSONB column value into ``list[str]``.

    psycopg with ``dict_row`` decodes JSONB into native Python types,
    so an array column comes back as a ``list``. Defensive cast in
    case the column ever materialises as ``None`` (no schema-level
    default protects this column today).
    """
    if value is None:
        return []
    return [str(item) for item in value]


async def fetch_recent_disruptions(
    pool: AsyncConnectionPool,
    *,
    limit: int,
    mode: Mode | None,
) -> list[DisruptionResponse]:
    """Return the most recent disruptions, optionally scoped to a mode."""
    params = {"limit": limit, "mode": mode}
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(DISRUPTIONS_SQL, params)
        rows: list[dict[str, Any]] = await cur.fetchall()

    return [
        DisruptionResponse(
            disruption_id=row["disruption_id"],
            category=row["category"],
            category_description=row["category_description"],
            description=row["description"],
            summary=row["summary"],
            affected_routes=_as_str_list(row["affected_routes"]),
            affected_stops=_as_str_list(row["affected_stops"]),
            closure_text=row["closure_text"],
            severity=int(row["severity"]),
            created=row["created"],
            last_update=row["last_update"],
        )
        for row in rows
    ]


async def fetch_bus_punctuality(
    pool: AsyncConnectionPool,
    *,
    stop_id: str,
    window: int,
) -> BusPunctualityResponse | None:
    """Return punctuality proxy for ``stop_id`` over the last ``window`` days.

    Returns ``None`` when no arrivals have been ingested for that stop
    in the window, or when the stop has never been seen at all
    (``station_name`` lookup misses).
    """
    params = {"stop_id": stop_id, "window": window}
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(BUS_PUNCTUALITY_SQL, params)
            agg = await cur.fetchone()
        if agg is None or not agg.get("sample_size"):
            return None
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(BUS_STOP_NAME_SQL, {"stop_id": stop_id})
            name_row = await cur.fetchone()

    if name_row is None or not name_row.get("station_name"):
        return None

    sample_size = int(agg["sample_size"])
    late_count = int(agg["late_count"])
    on_time_count = int(agg["on_time_count"])
    early_count = int(agg["early_count"])

    return BusPunctualityResponse(
        stop_id=stop_id,
        stop_name=str(name_row["station_name"]),
        window_days=window,
        on_time_percent=round(100.0 * on_time_count / sample_size, 1),
        early_percent=round(100.0 * early_count / sample_size, 1),
        late_percent=round(100.0 * late_count / sample_size, 1),
        sample_size=sample_size,
    )
