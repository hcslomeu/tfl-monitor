"""Hybrid NaPTAN ↔ station-name resolver.

Fast path queries ``analytics.dim_stations``; on miss, falls back to
``/StopPoint/{naptan_id}`` via :class:`TflClient`. A process-lifetime
in-memory cache absorbs repeated lookups across requests — station
names are stable, so a stale entry only matters during a TfL rename
(rare). ``None`` is cached for confirmed-miss codes (e.g. deprecated
NaPTANs) so unresolved codes don't trigger a TfL call per request.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Final

import logfire
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ingestion.tfl_client.client import TflClient

# Process-lifetime cache mapping NaPTAN → resolved name. ``None`` value
# means both the seed lookup and the TfL fallback returned nothing;
# preserved in the cache so repeated unresolved codes don't generate
# repeated TfL calls.
_NAPTAN_CACHE: dict[str, str | None] = {}

# Cap concurrent in-flight TfL lookups when several NaPTANs miss the
# seed at the same time. The free-tier TfL rate limit is 500 req/min
# per app-key; the API issues at most one /disruptions/recent per
# client per few seconds so 4 is comfortably under.
_TFL_LOOKUP_CONCURRENCY: Final = 4

_BATCH_LOOKUP_SQL: Final = """
SELECT naptan_id, name
FROM analytics.dim_stations
WHERE naptan_id = ANY(%(naptan_ids)s::text[])
"""


def _cache_clear() -> None:
    """Reset the module-level cache. Used by tests only."""
    _NAPTAN_CACHE.clear()


async def resolve_naptans(
    *,
    pool: AsyncConnectionPool,
    tfl_client: TflClient | None,
    naptan_ids: Iterable[str],
) -> dict[str, str | None]:
    """Resolve a batch of NaPTAN codes to station names.

    Returns a dict keyed by ``naptan_id`` with either the resolved
    human-readable name or ``None`` when both the seed and the TfL
    fallback failed. Missing NaPTANs (empty / falsy input) are
    silently dropped from the result.

    Args:
        pool: Open ``AsyncConnectionPool`` against the warehouse.
        tfl_client: Optional ``TflClient``. When ``None`` the fallback
            is skipped and unresolved NaPTANs map to ``None`` without
            being cached (so a future call with a wired client retries).
        naptan_ids: Iterable of NaPTAN codes to resolve. Duplicates are
            collapsed before any lookup happens.
    """
    unique_ids = {nid for nid in naptan_ids if nid}
    if not unique_ids:
        return {}

    result: dict[str, str | None] = {}
    pending: set[str] = set()
    for nid in unique_ids:
        if nid in _NAPTAN_CACHE:
            result[nid] = _NAPTAN_CACHE[nid]
        else:
            pending.add(nid)

    if pending:
        await _fast_path(pool, pending, result)

    if pending and tfl_client is not None:
        await _fallback_path(tfl_client, pending, result)

    for nid in pending:
        result[nid] = None
        if tfl_client is not None:
            _NAPTAN_CACHE[nid] = None

    return result


async def _fast_path(
    pool: AsyncConnectionPool,
    pending: set[str],
    result: dict[str, str | None],
) -> None:
    pending_list = list(pending)
    try:
        async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_BATCH_LOOKUP_SQL, {"naptan_ids": pending_list})
            rows = await cur.fetchall()
    except Exception:
        logfire.exception("stations.dim_lookup_failed", naptan_count=len(pending_list))
        return

    for row in rows:
        nid = str(row["naptan_id"])
        name = str(row["name"])
        result[nid] = name
        _NAPTAN_CACHE[nid] = name
        pending.discard(nid)


async def _fallback_path(
    tfl_client: TflClient,
    pending: set[str],
    result: dict[str, str | None],
) -> None:
    semaphore = asyncio.Semaphore(_TFL_LOOKUP_CONCURRENCY)

    async def _resolve_one(nid: str) -> tuple[str, str | None]:
        async with semaphore:
            try:
                stop_point = await tfl_client.fetch_stop_point(nid)
            except Exception:
                logfire.exception("stations.tfl_lookup_failed", naptan_id=nid)
                return nid, None
            return nid, stop_point.common_name

    pairs = await asyncio.gather(*(_resolve_one(nid) for nid in pending))
    for nid, name in pairs:
        result[nid] = name
        _NAPTAN_CACHE[nid] = name
        pending.discard(nid)
