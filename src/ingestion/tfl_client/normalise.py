"""Tier-1 → tier-2 normalisation for TfL responses.

Pure functions mapping the raw camelCase shapes returned by the TfL
Unified API (``contracts.schemas.tfl_api``) onto the snake_case tier-2
payloads in ``contracts.schemas.{line_status,arrivals,disruptions}``.
``disruption_payloads`` builds the shape that ``/api/v1/disruptions/recent``
returns; ``api.live`` consumes it so the synthetic-id and affected-stop
logic lives in one place.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import logfire

from contracts.schemas.arrivals import ArrivalPayload
from contracts.schemas.common import DisruptionCategory, TransportMode
from contracts.schemas.disruptions import DisruptionPayload
from contracts.schemas.line_status import LineStatusPayload
from contracts.schemas.tfl_api import (
    TflArrivalPrediction,
    TflLineResponse,
)

__all__ = [
    "arrival_payloads",
    "disruption_payloads",
    "line_status_payloads",
]

_DEFAULT_VALIDITY_HOURS = 12
_SUMMARY_MAX_LENGTH = 160
_SYNTHETIC_ID_HEX_LENGTH = 32


def line_status_payloads(
    response: list[TflLineResponse],
) -> list[LineStatusPayload]:
    """Flatten TfL ``Line`` records into one payload per validity window.

    Each entry in ``lineStatuses`` produces one payload per attached
    ``validityPeriods`` entry. Lines (or status entries) with no
    validity periods fall back to a single payload covering ``now`` to
    ``now + 12h`` — matching the convention exercised in
    ``tests/test_contracts.py``.

    Args:
        response: Tier-1 line records as returned by
            ``/Line/Mode/{modes}/Status``.

    Returns:
        Flat list of tier-2 :class:`LineStatusPayload` objects, in input
        order with stable iteration over ``lineStatuses`` and
        ``validityPeriods``.
    """
    fallback_now = datetime.now(UTC)
    fallback_until = fallback_now + timedelta(hours=_DEFAULT_VALIDITY_HOURS)
    payloads: list[LineStatusPayload] = []
    for line in response:
        try:
            mode = TransportMode(line.mode_name)
        except ValueError:
            logfire.warn(
                "tfl.normalise.unknown_transport_mode",
                line_id=line.id,
                mode_name=line.mode_name,
            )
            continue
        for status in line.line_statuses:
            common: dict[str, object] = {
                "line_id": line.id,
                "line_name": line.name,
                "mode": mode,
                "status_severity": status.status_severity,
                "status_severity_description": status.status_severity_description,
                "reason": status.reason,
            }
            if status.validity_periods:
                for period in status.validity_periods:
                    payloads.append(
                        LineStatusPayload(
                            **common,  # type: ignore[arg-type]
                            valid_from=period.from_date,
                            valid_to=period.to_date,
                        )
                    )
            else:
                payloads.append(
                    LineStatusPayload(
                        **common,  # type: ignore[arg-type]
                        valid_from=fallback_now,
                        valid_to=fallback_until,
                    )
                )
    return payloads


def arrival_payloads(
    response: list[TflArrivalPrediction],
) -> list[ArrivalPayload]:
    """Map tier-1 arrival predictions to tier-2 payloads.

    The tier-1 ``direction`` and ``destinationName`` fields are nullable
    in the upstream contract; tier-2 requires non-null strings, so empty
    strings are substituted when missing.

    Args:
        response: Tier-1 predictions as returned by
            ``/StopPoint/{id}/Arrivals``.

    Returns:
        Tier-2 :class:`ArrivalPayload` list in input order.
    """
    return [
        ArrivalPayload(
            arrival_id=item.id,
            station_id=item.naptan_id,
            station_name=item.station_name,
            line_id=item.line_id,
            platform_name=item.platform_name,
            direction=item.direction or "",
            destination=item.destination_name or "",
            expected_arrival=item.expected_arrival,
            time_to_station_seconds=item.time_to_station,
            vehicle_id=item.vehicle_id,
        )
        for item in response
    ]


def disruption_payloads(
    response: list[TflLineResponse],
) -> list[DisruptionPayload]:
    """Normalise nested disruption records into tier-2 payloads.

    Walks ``Line -> lineStatuses[] -> disruption`` over a response from
    ``/Line/Mode/{modes}/Status?detail=true``. The bare ``/Disruption``
    endpoint omits ``affectedRoutes`` and ``affectedStops`` on the free
    tier; only the detailed line-status payload populates them.

    Each populated ``disruption`` produces one tier-2 payload:

    - ``affected_routes``: a single-element list with the parent
      ``Line.id``. The nested ``disruption.affectedRoutes`` describes
      route sections of the parent line, not other lines, so the
      authoritative line identifier is the parent.
    - ``affected_stops``: the deduplicated list of ``naptanId`` values
      from ``disruption.affectedStops``.
    - ``disruption_id``: first ``32`` hex chars of a SHA-256 digest over
      ``{"category", "closure_text", "description": stripped,
      "affected_routes": sorted([...]), "affected_stops": sorted([...])}``.
      The nested-form payload does not expose the ``type`` field that
      the legacy ``/Disruption`` endpoint carried; the parent
      ``Line.id`` disambiguates across lines and the stop set
      disambiguates same-line dual disruptions that share
      ``category``/``closure_text``/``description`` (observed on
      District in the committed fixture).
    - ``created`` / ``last_update``: current UTC time. Downstream
      consumers must not rely on these for deduplication without a
      TfL-supplied key.
    - ``summary``: ``description`` truncated to 160 characters.
    - ``severity``: ``0``; the nested disruption record does not surface
      severity (the parent ``lineStatuses`` entry does, but it describes
      the line, not the disruption).

    Args:
        response: Tier-1 line-status records carrying nested disruptions.

    Returns:
        Tier-2 :class:`DisruptionPayload` list in walk order
        (line → lineStatus → disruption).
    """
    now = datetime.now(UTC)
    payloads: list[DisruptionPayload] = []
    for line in response:
        affected_routes = [line.id]
        for status in line.line_statuses:
            disruption = status.disruption
            if disruption is None:
                continue
            affected_stops = _extract_ids(disruption.affected_stops, "naptanId")
            closure_text = disruption.closure_text or ""
            try:
                category = DisruptionCategory(disruption.category)
            except ValueError:
                category = DisruptionCategory.UNDEFINED
            payloads.append(
                DisruptionPayload(
                    disruption_id=_synthetic_disruption_id(
                        category=disruption.category,
                        description=disruption.description,
                        closure_text=closure_text,
                        affected_routes=affected_routes,
                        affected_stops=affected_stops,
                    ),
                    category=category,
                    category_description=disruption.category_description,
                    description=disruption.description,
                    summary=disruption.description[:_SUMMARY_MAX_LENGTH],
                    affected_routes=affected_routes,
                    affected_stops=affected_stops,
                    closure_text=closure_text,
                    severity=0,
                    created=now,
                    last_update=now,
                )
            )
    return payloads


def _extract_ids(items: list[dict[str, object]], key: str) -> list[str]:
    """Return the deduplicated string values of ``key`` in first-seen order.

    Used for ``affected_stops`` extraction; the synthetic-ID hash sorts
    its inputs separately, so the helper's job is only to drop
    duplicates and preserve a stable iteration order for the exposed
    payload field.
    """
    extracted: list[str] = []
    seen: set[str] = set()
    for entry in items:
        value = entry.get(key)
        if isinstance(value, str) and value and value not in seen:
            extracted.append(value)
            seen.add(value)
    return extracted


def _synthetic_disruption_id(
    *,
    category: str,
    description: str,
    closure_text: str,
    affected_routes: list[str],
    affected_stops: list[str],
) -> str:
    """Build a stable synthetic disruption ID via SHA-256.

    The hash inputs are the fields TfL publishes on every nested
    disruption: ``category``, ``closure_text``, the whitespace-stripped
    ``description``, the sorted ``affected_routes`` (the parent
    ``Line.id``), and the sorted ``affected_stops``. ``affected_stops``
    is part of the digest because a single line can carry multiple
    ``lineStatuses`` entries whose nested disruptions share
    ``category`` / ``closure_text`` / ``description`` but list different
    route sections (e.g. the District-line ``Severe delays Turnham Green
    and Richmond / Ealing Broadway`` event appears twice on the same
    line with five and four affected stops respectively); without the
    stop set in the hash those two distinct incidents would collide on
    one ``disruption_id``. The built-in ``hash()`` is unsuitable here
    because it is randomised per Python process (``PYTHONHASHSEED``).
    """
    payload = json.dumps(
        {
            "category": category,
            "closure_text": closure_text,
            "description": description.strip(),
            "affected_routes": sorted(affected_routes),
            "affected_stops": sorted(affected_stops),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return digest[:_SYNTHETIC_ID_HEX_LENGTH]
