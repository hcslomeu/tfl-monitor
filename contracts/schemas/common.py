"""Shared enums, envelope, and type aliases for TfL event contracts."""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TransportMode(StrEnum):
    """TfL transport modes served by this platform."""

    TUBE = "tube"
    ELIZABETH_LINE = "elizabeth-line"
    OVERGROUND = "overground"
    DLR = "dlr"
    BUS = "bus"
    NATIONAL_RAIL = "national-rail"
    RIVER_BUS = "river-bus"
    CABLE_CAR = "cable-car"
    TRAM = "tram"


class StatusSeverity(IntEnum):
    """TfL line status severity codes (0 = worst, 10 = good service, 20 = closed)."""

    SPECIAL_SERVICE = 0
    CLOSED = 1
    SUSPENDED = 2
    PART_SUSPENDED = 3
    PLANNED_CLOSURE = 4
    PART_CLOSURE = 5
    SEVERE_DELAYS = 6
    REDUCED_SERVICE = 7
    BUS_SERVICE = 8
    MINOR_DELAYS = 9
    GOOD_SERVICE = 10
    PART_CLOSED = 11
    EXIT_ONLY = 12
    NO_STEP_FREE_ACCESS = 13
    CHANGE_OF_FREQUENCY = 14
    DIVERTED = 15
    NOT_RUNNING = 16
    ISSUES_REPORTED = 17
    NO_ISSUES = 18
    INFORMATION = 19
    SERVICE_CLOSED = 20


class DisruptionCategory(StrEnum):
    """Top-level category for a TfL disruption record."""

    REAL_TIME = "RealTime"
    PLANNED_WORK = "PlannedWork"
    INFORMATION = "Information"
    INCIDENT = "Incident"
    UNDEFINED = "Undefined"


LineId = str
StationId = str


class Event[P: BaseModel](BaseModel):
    """Immutable envelope serialised to Kafka as JSON.

    Attributes:
        event_id: Unique event identifier (UUIDv7 preferred).
        event_type: Event-type discriminator for consumers.
        source: Fixed upstream origin.
        ingested_at: UTC timestamp when the event was ingested.
        payload: Typed payload specific to the topic.
    """

    model_config = ConfigDict(frozen=True)

    event_id: UUID = Field(..., description="Unique event identifier (UUIDv7 preferred)")
    event_type: str = Field(..., description="Event type discriminator")
    source: Literal["tfl-unified-api"] = "tfl-unified-api"
    ingested_at: datetime = Field(..., description="UTC timestamp when ingested")
    payload: P

    TOPIC_NAME: ClassVar[str]
