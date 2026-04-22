"""Pydantic contracts for TfL Kafka topics and the upstream TfL API.

Two tiers:

- **Tier-2 Kafka events** (default export) — our internal wire format,
  snake_case, produced by ingestion and consumed downstream.
- **Tier-1 TfL API payloads** (`tfl_api` submodule) — raw shapes returned
  by ``api.tfl.gov.uk``. Normalised into tier-2 by the ingestion client.
"""

from contracts.schemas.arrivals import ArrivalEvent, ArrivalPayload
from contracts.schemas.common import (
    DisruptionCategory,
    Event,
    LineId,
    StationId,
    StatusSeverity,
    TransportMode,
)
from contracts.schemas.disruptions import DisruptionEvent, DisruptionPayload
from contracts.schemas.line_status import LineStatusEvent, LineStatusPayload
from contracts.schemas.tfl_api import (
    TflArrivalPrediction,
    TflDisruption,
    TflLineResponse,
    TflLineStatusDisruption,
    TflLineStatusItem,
    TflValidityPeriod,
)

__all__ = [
    "ArrivalEvent",
    "ArrivalPayload",
    "DisruptionCategory",
    "DisruptionEvent",
    "DisruptionPayload",
    "Event",
    "LineId",
    "LineStatusEvent",
    "LineStatusPayload",
    "StationId",
    "StatusSeverity",
    "TflArrivalPrediction",
    "TflDisruption",
    "TflLineResponse",
    "TflLineStatusDisruption",
    "TflLineStatusItem",
    "TflValidityPeriod",
    "TransportMode",
]
