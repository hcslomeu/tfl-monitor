"""Arrival event contract."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from contracts.schemas.common import Event


class ArrivalPayload(BaseModel):
    """Predicted arrival of a vehicle at a specific stop point."""

    model_config = ConfigDict(frozen=True)

    arrival_id: str = Field(..., description="TfL prediction identifier")
    station_id: str = Field(..., description="TfL stop-point identifier (NaPTAN)")
    station_name: str = Field(..., description="Human-readable station name")
    line_id: str = Field(..., description="TfL line identifier")
    platform_name: str = Field(..., description="Platform label (e.g. 'Northbound - Platform 1')")
    direction: str = Field(..., description="Travel direction (inbound / outbound / etc.)")
    destination: str = Field(..., description="Headsign or terminating station")
    expected_arrival: datetime = Field(..., description="Predicted arrival timestamp (UTC)")
    time_to_station_seconds: int = Field(
        ..., ge=0, description="Seconds until predicted arrival at the stop"
    )
    vehicle_id: str | None = Field(
        default=None, description="Running number / vehicle identifier, when available"
    )


class ArrivalEvent(Event[ArrivalPayload]):
    """Kafka event carrying an arrival prediction."""

    TOPIC_NAME: ClassVar[str] = "arrivals"
