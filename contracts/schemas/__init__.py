"""Pydantic contracts for the upstream TfL API and normalised shapes.

- **Tier-1 TfL API payloads** (``tfl_api`` submodule): raw shapes returned
  by ``api.tfl.gov.uk``.
- **Normalised shapes** (default export): snake_case records derived from
  tier-1 by ``ingestion.tfl_client.normalise`` and served by the API.
"""

from contracts.schemas.common import (
    DisruptionCategory,
    LineId,
    StationId,
    StatusSeverity,
    TransportMode,
)
from contracts.schemas.disruptions import DisruptionPayload
from contracts.schemas.tfl_api import (
    TflArrivalPrediction,
    TflLineResponse,
    TflLineStatusDisruption,
    TflLineStatusItem,
    TflValidityPeriod,
)

__all__ = [
    "DisruptionCategory",
    "DisruptionPayload",
    "LineId",
    "StationId",
    "StatusSeverity",
    "TflArrivalPrediction",
    "TflLineResponse",
    "TflLineStatusDisruption",
    "TflLineStatusItem",
    "TflValidityPeriod",
    "TransportMode",
]
