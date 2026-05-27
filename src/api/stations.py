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

import httpx
import logfire
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ingestion.tfl_client.client import TflClient, TflClientError

# Process-lifetime cache mapping NaPTAN → resolved name. ``None`` value
# means the resolver definitively confirmed the code is unknown
# (warehouse miss + TfL 404). Transient failures (timeouts, 5xx) are
# *not* cached so the next request retries the lookup.
_NAPTAN_CACHE: dict[str, str | None] = {}

# Process-lifetime cache mapping a normalised free-text station query →
# resolved StopPoint/NaPTAN id. ``None`` means the search returned no
# matches (a definitive HTTP 200 miss). Transient failures (timeouts,
# 5xx, network errors) are *not* cached so the next request retries.
_NAME_CACHE: dict[str, str | None] = {}

# Cap concurrent in-flight TfL lookups across all requests when several
# NaPTANs miss the seed at the same time. The free-tier TfL rate limit
# is 500 req/min per app-key; sharing one semaphore per process keeps
# burst concurrency bounded even under simultaneous requests.
_TFL_LOOKUP_CONCURRENCY: Final = 4
_TFL_SEMAPHORE: asyncio.Semaphore | None = None

_BATCH_LOOKUP_SQL: Final = """
SELECT naptan_id, name
FROM analytics.dim_stations
WHERE naptan_id = ANY(%(naptan_ids)s::text[])
"""


def _cache_clear() -> None:
    """Reset the module-level caches and semaphore. Used by tests only."""
    global _TFL_SEMAPHORE
    _NAPTAN_CACHE.clear()
    _NAME_CACHE.clear()
    _TFL_SEMAPHORE = None


def _get_tfl_semaphore() -> asyncio.Semaphore:
    """Return the shared TfL-lookup semaphore, lazily binding to the loop."""
    global _TFL_SEMAPHORE
    if _TFL_SEMAPHORE is None:
        _TFL_SEMAPHORE = asyncio.Semaphore(_TFL_LOOKUP_CONCURRENCY)
    return _TFL_SEMAPHORE


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
    """Resolve outstanding NaPTANs via TfL ``/StopPoint/{id}``.

    Caches successful lookups and confirmed 404 misses; leaves transient
    failures (timeouts, 5xx, network errors) uncached so a future request
    retries them instead of surfacing ``Unknown`` for the rest of the
    process lifetime.
    """
    semaphore = _get_tfl_semaphore()

    async def _resolve_one(nid: str) -> tuple[str, str | None, bool]:
        async with semaphore:
            try:
                stop_point = await tfl_client.fetch_stop_point(nid)
            except TflClientError as exc:
                is_definitive_miss = _is_not_found(exc)
                if not is_definitive_miss:
                    logfire.exception("stations.tfl_lookup_failed", naptan_id=nid)
                return nid, None, is_definitive_miss
            except Exception:
                logfire.exception("stations.tfl_lookup_failed", naptan_id=nid)
                return nid, None, False
            return nid, stop_point.common_name, True

    pairs = await asyncio.gather(*(_resolve_one(nid) for nid in pending))
    for nid, name, is_definitive in pairs:
        result[nid] = name
        if is_definitive:
            _NAPTAN_CACHE[nid] = name
        pending.discard(nid)


def _is_not_found(exc: TflClientError) -> bool:
    """True when the underlying httpx error was a 404 (vs transient failure)."""
    cause = exc.__cause__
    return isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code == 404


async def resolve_name(*, tfl_client: TflClient | None, query: str) -> str | None:
    """Resolve a free-text station name to a StopPoint/NaPTAN id.

    Searches TfL ``/StopPoint/Search`` and returns the top-ranked match's
    id. A process-lifetime cache absorbs repeated queries: definitive
    no-match results (empty matches) are cached as ``None`` so they cost
    nothing to repeat, while transient failures are left uncached so the
    next call retries.

    Args:
        tfl_client: Optional ``TflClient``. When ``None`` the function
            returns ``None`` without caching.
        query: Free-text station name (e.g. ``"Oxford Circus"``).

    Returns:
        The resolved StopPoint/NaPTAN id, or ``None`` when the query is
        empty, unresolved, or no client is available.
    """
    if tfl_client is None:
        return None
    normalised = query.strip().lower()
    if not normalised:
        return None
    if normalised in _NAME_CACHE:
        return _NAME_CACHE[normalised]

    semaphore = _get_tfl_semaphore()
    async with semaphore:
        try:
            response = await tfl_client.search_stop(normalised)
        except Exception:
            logfire.exception("stations.name_search_failed", query=normalised)
            return None

    resolved = response.matches[0].id if response.matches else None
    _NAME_CACHE[normalised] = resolved
    return resolved
