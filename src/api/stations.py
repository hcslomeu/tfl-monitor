"""NaPTAN ↔ station-name resolver backed by the TfL ``/StopPoint`` API.

Reverse lookups hit ``/StopPoint/{naptan_id}`` via :class:`TflClient`. A
process-lifetime in-memory cache absorbs repeated lookups across
requests — station names are stable, so a stale entry only matters
during a TfL rename (rare). ``None`` is cached for confirmed-miss codes
(e.g. deprecated NaPTANs) so unresolved codes don't trigger a TfL call
per request.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Final

import httpx
import logfire

from contracts.schemas.tfl_api import TflStopPoint
from ingestion.tfl_client.client import TflClient, TflClientError

# Process-lifetime cache mapping NaPTAN → resolved name. ``None`` value
# means the resolver definitively confirmed the code is unknown
# (TfL 404). Transient failures (timeouts, 5xx) are
# *not* cached so the next request retries the lookup.
_NAPTAN_CACHE: dict[str, str | None] = {}

# Process-lifetime cache mapping a normalised free-text station query →
# resolved StopPoint/NaPTAN id. ``None`` means the search returned no
# matches (a definitive HTTP 200 miss). Transient failures (timeouts,
# 5xx, network errors) are *not* cached so the next request retries.
# Keys are arbitrary user text, so the cache is bounded with simple FIFO
# eviction to keep memory flat under high-cardinality chat traffic.
_NAME_CACHE: dict[str, str | None] = {}
_NAME_CACHE_MAX: Final = 512

# TfL Search ranks a hub id (prefixed ``HUB``) top for major interchanges,
# but a hub id is not a usable journey/arrival endpoint — it must be
# dereferenced to a concrete rail child, preferred by this mode order.
_HUB_PREFIX: Final = "HUB"
_RAIL_MODE_PRIORITY: Final = ("tube", "elizabeth-line", "dlr", "overground", "national-rail")

# Cap concurrent in-flight TfL lookups across all requests when several
# NaPTANs miss the cache at the same time. The free-tier TfL rate limit
# is 500 req/min per app-key; sharing one semaphore per process keeps
# burst concurrency bounded even under simultaneous requests.
_TFL_LOOKUP_CONCURRENCY: Final = 4
_TFL_SEMAPHORE: asyncio.Semaphore | None = None

# Wall-clock budget for one batch of uncached NaPTAN lookups. Names only
# decorate disruption cards, so ids still unresolved at the deadline come
# back as ``None`` (uncached) instead of letting a slow ``/StopPoint``
# (30 s timeout x 3 attempts per call) run past the function time limit.
_LOOKUP_DEADLINE_SECONDS: Final = 10.0


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
    tfl_client: TflClient | None,
    naptan_ids: Iterable[str],
) -> dict[str, str | None]:
    """Resolve a batch of NaPTAN codes to station names.

    Returns a dict keyed by ``naptan_id`` with either the resolved
    human-readable name or ``None`` when the TfL lookup failed. Missing
    NaPTANs (empty / falsy input) are silently dropped from the result.

    Args:
        tfl_client: Optional ``TflClient``. When ``None`` the lookup
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

    if pending and tfl_client is not None:
        await _lookup(tfl_client, pending, result)

    for nid in pending:
        result[nid] = None

    return result


async def _lookup(
    tfl_client: TflClient,
    pending: set[str],
    result: dict[str, str | None],
) -> None:
    """Resolve outstanding NaPTANs via TfL ``/StopPoint/{id}``.

    Caches successful lookups and confirmed 404 misses; leaves transient
    failures (timeouts, 5xx, network errors) uncached so a future request
    retries them instead of surfacing ``Unknown`` for the rest of the
    process lifetime. Lookups still running after
    ``_LOOKUP_DEADLINE_SECONDS`` are cancelled and stay in ``pending``.
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

    tasks = [asyncio.create_task(_resolve_one(nid)) for nid in pending]
    done, unfinished = await asyncio.wait(tasks, timeout=_LOOKUP_DEADLINE_SECONDS)
    if unfinished:
        for task in unfinished:
            task.cancel()
        await asyncio.gather(*unfinished, return_exceptions=True)
        logfire.warning("stations.lookup_deadline_exceeded", unresolved=len(unfinished))
    for task in done:
        nid, name, is_definitive = task.result()
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
    query = query.strip()
    if not query:
        return None
    # Lowercase only the cache key, never the value sent upstream: TfL
    # Search is case-insensitive for names, but folding case on a NaPTAN
    # id could break an exact-id lookup.
    cache_key = query.lower()
    if cache_key in _NAME_CACHE:
        return _NAME_CACHE[cache_key]

    semaphore = _get_tfl_semaphore()
    async with semaphore:
        try:
            response = await tfl_client.search_stop(query)
        except Exception:
            logfire.exception("stations.name_search_failed", query=cache_key)
            return None

    resolved = response.matches[0].id if response.matches else None
    if resolved is not None and resolved.startswith(_HUB_PREFIX):
        try:
            resolved = await _deref_hub(tfl_client, resolved)
        except Exception:
            # A transient hub lookup failure must NOT be cached: return the
            # unusable hub id for this call but leave the cache untouched so
            # the next request retries the dereference (mirrors the reverse
            # resolver's "don't poison the cache on a hiccup" stance).
            logfire.exception("stations.hub_deref_failed", hub_id=resolved)
            return resolved
    if len(_NAME_CACHE) >= _NAME_CACHE_MAX:
        _NAME_CACHE.pop(next(iter(_NAME_CACHE)))
    _NAME_CACHE[cache_key] = resolved
    return resolved


async def _deref_hub(tfl_client: TflClient, hub_id: str) -> str:
    """Resolve a hub id to a concrete rail child NaPTAN.

    Hub ids (``HUB*``) are rejected by journey planning and return no
    arrivals, so fetch the hub stop point and pick the highest-priority
    rail child. Returns the hub id unchanged when the hub exposes no rail
    child (a definitive result, safe to cache). Propagates the underlying
    error on a transient lookup failure so the caller can avoid caching.
    """
    async with _get_tfl_semaphore():
        stop_point = await tfl_client.fetch_stop_point(hub_id)
    return _pick_rail_child(stop_point) or hub_id


def _pick_rail_child(stop_point: TflStopPoint) -> str | None:
    """Return the NaPTAN of the highest-priority rail child, or ``None``."""
    for mode in _RAIL_MODE_PRIORITY:
        for child in stop_point.children:
            if mode in child.modes:
                return child.naptan_id
    return None
