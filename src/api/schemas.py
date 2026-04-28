"""Pydantic v2 response models for the API.

Mirrors ``contracts/openapi.yaml`` ``LineStatus`` and ``LineReliability``
schemas. Kept separate from ``contracts/schemas/*`` (Kafka tier) so the
wire format and the API response can evolve independently.
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


class Problem(BaseModel):
    """RFC 7807 ``application/problem+json`` body."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
