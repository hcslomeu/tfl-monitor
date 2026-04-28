"""Pydantic v2 response models for the API.

Mirrors ``contracts/openapi.yaml`` ``LineStatus``, ``LineReliability``,
``Disruption`` and ``BusPunctuality`` schemas. Kept separate from
``contracts/schemas/*`` (Kafka tier) so the wire format and the API
response can evolve independently.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal[
    "tube",
    "elizabeth-line",
    "overground",
    "dlr",
    "bus",
    "national-rail",
    "river-bus",
    "cable-car",
    "tram",
]

DisruptionCategory = Literal[
    "RealTime",
    "PlannedWork",
    "Information",
    "Incident",
    "Undefined",
]


class LineStatusResponse(BaseModel):
    """Live or historical operational status for a single line."""

    model_config = ConfigDict(extra="forbid")

    line_id: str
    line_name: str
    mode: Mode
    status_severity: int = Field(ge=0, le=20)
    status_severity_description: str
    reason: str | None = None
    valid_from: datetime
    valid_to: datetime


class LineReliabilityResponse(BaseModel):
    """Reliability aggregate for a single line over a rolling window."""

    model_config = ConfigDict(extra="forbid")

    line_id: str
    line_name: str
    mode: str
    window_days: int = Field(ge=1, le=90)
    reliability_percent: float = Field(ge=0.0, le=100.0)
    sample_size: int = Field(ge=0)
    severity_histogram: dict[str, int]


class DisruptionResponse(BaseModel):
    """Single disruption record surfaced by ``/api/v1/disruptions/recent``."""

    model_config = ConfigDict(extra="forbid")

    disruption_id: str
    category: DisruptionCategory
    category_description: str
    description: str
    summary: str
    affected_routes: list[str]
    affected_stops: list[str]
    closure_text: str
    severity: int = Field(ge=0)
    created: datetime
    last_update: datetime


class BusPunctualityResponse(BaseModel):
    """Punctuality summary surfaced by ``/api/v1/bus/{stop_id}/punctuality``.

    The on-time / early / late percentages are a documented proxy
    composed in SQL on top of ``time_to_station_seconds`` — TfL does
    not publish actual departure events, so the percentages reflect
    the distribution of arrival predictions, not realised arrivals.
    See ``BUS_PUNCTUALITY_SQL`` in ``api.db`` for the bucket
    definitions and the rationale for the 5-minute threshold.
    """

    model_config = ConfigDict(extra="forbid")

    stop_id: str
    stop_name: str
    window_days: int = Field(ge=1, le=90)
    on_time_percent: float = Field(ge=0.0, le=100.0)
    early_percent: float = Field(ge=0.0, le=100.0)
    late_percent: float = Field(ge=0.0, le=100.0)
    sample_size: int = Field(ge=0)


class Problem(BaseModel):
    """RFC 7807 ``application/problem+json`` body."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


class ChatRequest(BaseModel):
    """Body of ``POST /api/v1/chat/stream``.

    Mirrors the OpenAPI ``ChatRequest`` schema; ``extra="forbid"`` so a
    malformed client cannot smuggle additional fields past the route
    boundary.
    """

    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=4000)


class ChatMessageResponse(BaseModel):
    """Single chat turn returned by ``GET /api/v1/chat/{thread_id}/history``.

    Mirrors the OpenAPI ``ChatMessage`` schema.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime
