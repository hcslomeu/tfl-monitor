"""TfL live read-through layer for the API service.

Reads current network state directly from the TfL Unified API on each
request (ADR 014 — the ``raw.*`` warehouse was decommissioned). Mirrors
the role :mod:`api.db` plays for Postgres: it returns the same response
schemas the endpoints and agent tools consume, sourced live instead of
from SQL. Disruption normalisation is reused from
:mod:`ingestion.tfl_client.normalise` so the synthetic-id and
affected-stop logic stays in one place.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import cast

from psycopg_pool import AsyncConnectionPool

from api.schemas import (
    AffectedStop,
    DisruptionResponse,
    LineStatusResponse,
    Mode,
)
from api.stations import resolve_naptans
from contracts.schemas.tfl_api import TflLineStatusItem
from ingestion.tfl_client.client import TflClient
from ingestion.tfl_client.normalise import disruption_payloads

# The four modes the dashboard surfaces as line status. TfL's ``bus``
# mode would return several hundred lines per call and the dashboard's
# bus surface is a separate feature, so it is intentionally excluded.
DEFAULT_STATUS_MODES: tuple[str, ...] = ("tube", "elizabeth-line", "overground", "dlr")

_VALID_MODES: frozenset[str] = frozenset(Mode.__args__)  # type: ignore[attr-defined]
_GOOD_SERVICE_SEVERITY = 10
_FALLBACK_VALIDITY = timedelta(hours=12)


async def fetch_live_status(
    tfl_client: TflClient,
    *,
    modes: Sequence[str] = DEFAULT_STATUS_MODES,
) -> list[LineStatusResponse]:
    """Return current operational status, one row per line, read live from TfL.

    Args:
        tfl_client: Active TfL client.
        modes: TfL transport modes to query.

    Returns:
        One :class:`LineStatusResponse` per line. Lines whose mode is not
        in the API ``Mode`` set are skipped.
    """
    lines = await tfl_client.fetch_line_statuses(modes)
    now = datetime.now(UTC)
    results: list[LineStatusResponse] = []
    for line in lines:
        if line.mode_name not in _VALID_MODES:
            continue
        status = _primary_status(line.line_statuses)
        if status is None:
            continue
        valid_from, valid_to = _validity_window(status, now)
        results.append(
            LineStatusResponse(
                line_id=line.id,
                line_name=line.name,
                mode=cast(Mode, line.mode_name),
                status_severity=status.status_severity,
                status_severity_description=status.status_severity_description,
                reason=status.reason,
                valid_from=valid_from,
                valid_to=valid_to,
            )
        )
    return results


async def fetch_recent_disruptions(
    tfl_client: TflClient,
    *,
    pool: AsyncConnectionPool,
    limit: int,
    mode: Mode | None,
    modes: Sequence[str] = DEFAULT_STATUS_MODES,
) -> list[DisruptionResponse]:
    """Return current disruptions, read live from ``/Status?detail=true``.

    The bare ``/Disruption`` endpoint omits ``affectedRoutes`` and
    ``affectedStops`` on the free tier, so the detailed line-status call
    is the only source that populates them. Each disruption's NaPTAN
    stops are resolved to station names via
    :func:`api.stations.resolve_naptans` (dim_stations fast path + TfL
    fallback).

    Args:
        tfl_client: Active TfL client.
        pool: Open pool, used by the station-name resolver.
        limit: Maximum number of disruptions to return.
        mode: When given, restricts the query to that single mode;
            otherwise the dashboard's default modes are queried.
        modes: Default modes queried when ``mode`` is ``None``.

    Returns:
        Up to ``limit`` :class:`DisruptionResponse` records in walk order.
    """
    query_modes: Sequence[str] = (mode,) if mode is not None else modes
    lines = await tfl_client.fetch_line_disruptions(query_modes)
    payloads = disruption_payloads(lines)

    all_naptan_ids = {nid for payload in payloads for nid in payload.affected_stops}
    name_by_naptan = await resolve_naptans(
        pool=pool,
        tfl_client=tfl_client,
        naptan_ids=all_naptan_ids,
    )

    results = [
        DisruptionResponse(
            disruption_id=payload.disruption_id,
            category=payload.category.value,
            category_description=payload.category_description,
            description=payload.description,
            summary=payload.summary,
            affected_routes=list(dict.fromkeys(payload.affected_routes)),
            affected_stops=[
                AffectedStop(naptan_id=nid, name=name_by_naptan.get(nid))
                for nid in dict.fromkeys(payload.affected_stops)
            ],
            closure_text=payload.closure_text,
            severity=payload.severity,
            created=payload.created,
            last_update=payload.last_update,
        )
        for payload in payloads
    ]
    return results[:limit]


def _primary_status(statuses: list[TflLineStatusItem]) -> TflLineStatusItem | None:
    """Pick the one status that best represents a line's current state.

    A line can carry multiple ``lineStatuses`` entries. Surface a
    disruption over Good Service (TfL severity ``10``); among
    disruptions, the lowest severity number (the worst delay/closure)
    wins. Returns ``None`` when the line has no status entries.
    """
    if not statuses:
        return None
    return min(
        statuses,
        key=lambda status: (
            status.status_severity == _GOOD_SERVICE_SEVERITY,
            status.status_severity,
        ),
    )


def _validity_window(status: TflLineStatusItem, now: datetime) -> tuple[datetime, datetime]:
    """Return the validity window for a status, falling back to ``now + 12h``.

    Matches the fallback convention in
    :func:`ingestion.tfl_client.normalise.line_status_payloads` for
    statuses with no validity periods.
    """
    if status.validity_periods:
        period = status.validity_periods[0]
        return period.from_date, period.to_date
    return now, now + _FALLBACK_VALIDITY
