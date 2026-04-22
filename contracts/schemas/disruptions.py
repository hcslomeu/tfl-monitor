"""Disruption event contract."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from contracts.schemas.common import DisruptionCategory, Event


class DisruptionPayload(BaseModel):
    """Reported disruption affecting one or more TfL routes or stops."""

    model_config = ConfigDict(frozen=True)

    disruption_id: str = Field(..., description="TfL disruption identifier")
    category: DisruptionCategory = Field(..., description="Top-level disruption category")
    category_description: str = Field(
        ..., description="Human-readable category label as published by TfL"
    )
    description: str = Field(..., description="Full disruption description")
    summary: str = Field(..., description="Short disruption summary")
    affected_routes: list[str] = Field(
        default_factory=list, description="Line IDs impacted by the disruption"
    )
    affected_stops: list[str] = Field(
        default_factory=list, description="Stop-point IDs impacted by the disruption"
    )
    closure_text: str = Field(..., description="Closure text as published (may be empty)")
    severity: int = Field(..., ge=0, description="Disruption severity scale")
    created: datetime = Field(..., description="When the disruption was first published (UTC)")
    last_update: datetime = Field(..., description="Last update timestamp (UTC)")


class DisruptionEvent(Event[DisruptionPayload]):
    """Kafka event carrying a disruption record."""

    TOPIC_NAME: ClassVar[str] = "disruptions"
