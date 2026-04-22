"""Line-status event contract."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.schemas.common import Event, TransportMode


class LineStatusPayload(BaseModel):
    """Snapshot of a TfL line's operational status over a validity window."""

    model_config = ConfigDict(frozen=True)

    line_id: str = Field(..., description="TfL line identifier (e.g. 'victoria')")
    line_name: str = Field(..., description="Human-readable line name")
    mode: TransportMode = Field(..., description="Transport mode of the line")
    status_severity: int = Field(..., ge=0, le=20, description="TfL severity code 0-20")
    status_severity_description: str = Field(
        ..., description="Human-readable status description (e.g. 'Good Service')"
    )
    reason: str | None = Field(default=None, description="Cause of disruption, when present")
    valid_from: datetime = Field(..., description="Start of the validity window (UTC)")
    valid_to: datetime = Field(..., description="End of the validity window (UTC)")

    @model_validator(mode="after")
    def _validity_window(self) -> Self:
        if self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be strictly greater than valid_from")
        return self


class LineStatusEvent(Event[LineStatusPayload]):
    """Kafka event carrying a line-status snapshot."""

    TOPIC_NAME: ClassVar[str] = "line-status"
