"""Tier-1 → tier-2 normalisation for TfL ingestion.

Pure functions mapping the raw camelCase shapes returned by the TfL
Unified API (``contracts.schemas.tfl_api``) onto the snake_case Kafka
payloads consumed by downstream services
(``contracts.schemas.{line_status,arrivals,disruptions}``).

Wrapping payloads into :class:`Event` envelopes (``event_id``,
``ingested_at``, …) is intentionally left to the producers (TM-B2):
those fields depend on Kafka delivery context and per-event UUID
generation, neither of which belong in a pure data adapter.
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
    TflDisruption,
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
    response: list[TflDisruption],
) -> list[DisruptionPayload]:
    """Normalise TfL disruption records into tier-2 payloads.

    The free TfL ``/Line/Mode/{mode}/Disruption`` endpoint omits stable
    identifiers (no ``id``, ``created`` or ``severity`` fields), so this
    adapter synthesises:

    - ``disruption_id``: first ``32`` hex chars of a SHA-256 digest over
      ``{"category", "description": stripped, "affected_routes": sorted([...])}``,
      stable across processes (Python's built-in ``hash()`` is
      randomised per process and is therefore not used). The description
      is ``.strip()``-normalised so trivial upstream whitespace changes
      do not invalidate the synthetic ID.
    - ``created`` / ``last_update``: current UTC time. Downstream
      consumers must not rely on these for deduplication without a
      TfL-supplied key.
    - ``summary``: ``description`` truncated to 160 characters; the TfL
      free endpoint does not return a separate summary field.
    - ``severity``: ``0``; the endpoint does not surface severity.

    Args:
        response: Tier-1 disruption records.

    Returns:
        Tier-2 :class:`DisruptionPayload` list in input order.
    """
    now = datetime.now(UTC)
    payloads: list[DisruptionPayload] = []
    for item in response:
        affected_routes = _extract_ids(item.affected_routes, "lineId")
        affected_stops = _extract_ids(item.affected_stops, "naptanId")
        try:
            category = DisruptionCategory(item.category)
        except ValueError:
            category = DisruptionCategory.UNDEFINED
        payloads.append(
            DisruptionPayload(
                disruption_id=_synthetic_disruption_id(
                    category=item.category,
                    description=item.description,
                    affected_routes=affected_routes,
                ),
                category=category,
                category_description=item.category_description,
                description=item.description,
                summary=item.description[:_SUMMARY_MAX_LENGTH],
                affected_routes=affected_routes,
                affected_stops=affected_stops,
                closure_text=item.closure_text or "",
                severity=0,
                created=now,
                last_update=now,
            )
        )
    return payloads


def _extract_ids(items: list[dict[str, object]], key: str) -> list[str]:
    """Return the string values of ``key`` across a list of dict entries.

    For TfL ``affectedRoutes`` entries the correct key is ``lineId`` (the
    parent line identifier) rather than ``id`` (which identifies the
    specific route segment); ``DisruptionPayload.affected_routes`` is
    documented as a list of line identifiers, so consumers join on it.
    """
    extracted: list[str] = []
    for entry in items:
        value = entry.get(key)
        if isinstance(value, str) and value:
            extracted.append(value)
    return extracted


def _synthetic_disruption_id(
    *,
    category: str,
    description: str,
    affected_routes: list[str],
) -> str:
    """Build a stable synthetic disruption ID via SHA-256.

    The built-in ``hash()`` is unsuitable here because it is randomised
    per Python process (PYTHONHASHSEED) and therefore unstable across
    runs and workers.
    """
    payload = json.dumps(
        {
            "category": category,
            "description": description.strip(),
            "affected_routes": sorted(affected_routes),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return digest[:_SYNTHETIC_ID_HEX_LENGTH]
