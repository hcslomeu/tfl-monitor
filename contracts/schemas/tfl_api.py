"""Tier-1 contracts describing raw responses from the TfL Unified API.

These models validate the JSON we receive from
``https://api.tfl.gov.uk`` *before* normalisation. They intentionally
mirror the TfL-side camelCase shape and cover only the fields the
ingestion layer (TM-B*) consumes; every other attribute in the payload
is discarded via ``extra="ignore"``.

Normalisation from these shapes into the tier-2 Kafka events defined in
:mod:`contracts.schemas` is the responsibility of the ingestion client.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


def _tfl_model_config() -> ConfigDict:
    return ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        frozen=True,
    )


class TflValidityPeriod(BaseModel):
    """Single validity window attached to a line-status entry."""

    model_config = _tfl_model_config()

    from_date: datetime
    to_date: datetime
    is_now: bool


class TflLineStatusDisruption(BaseModel):
    """Disruption object nested inside a line-status entry."""

    model_config = _tfl_model_config()

    category: str
    category_description: str
    description: str
    affected_routes: list[dict[str, object]] = Field(default_factory=list)
    affected_stops: list[dict[str, object]] = Field(default_factory=list)
    closure_text: str | None = None


class TflLineStatusItem(BaseModel):
    """Individual status entry within a TfL ``Line`` record."""

    model_config = _tfl_model_config()

    line_id: str | None = None
    status_severity: int = Field(ge=0, le=20)
    status_severity_description: str
    reason: str | None = None
    validity_periods: list[TflValidityPeriod] = Field(default_factory=list)
    disruption: TflLineStatusDisruption | None = None


class TflLineResponse(BaseModel):
    """Top-level TfL ``Line`` record returned by ``/Line/Mode/{mode}/Status``."""

    model_config = _tfl_model_config()

    id: str
    name: str
    mode_name: str
    line_statuses: list[TflLineStatusItem] = Field(default_factory=list)


class TflArrivalPrediction(BaseModel):
    """Prediction record returned by ``/StopPoint/{id}/Arrivals``."""

    model_config = _tfl_model_config()

    id: str
    naptan_id: str
    station_name: str
    line_id: str
    line_name: str
    platform_name: str
    direction: str | None = None
    destination_name: str | None = None
    expected_arrival: datetime
    time_to_station: int = Field(ge=0)
    vehicle_id: str | None = None
    mode_name: str


class TflDisruption(BaseModel):
    """Disruption record returned by ``/Line/Mode/{mode}/Disruption``."""

    model_config = _tfl_model_config()

    category: str
    category_description: str
    description: str
    affected_routes: list[dict[str, object]] = Field(default_factory=list)
    affected_stops: list[dict[str, object]] = Field(default_factory=list)
    closure_text: str | None = None
    type: str | None = None
