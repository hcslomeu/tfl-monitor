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
    """Disruption object nested inside a line-status entry.

    The nested ``affectedRoutes`` array is intentionally dropped from
    this model: the producer treats the parent ``Line.id`` as the
    affected line and the nested route-section structure has no
    downstream consumer. ``extra="ignore"`` silently discards it.
    """

    model_config = _tfl_model_config()

    category: str
    category_description: str
    description: str
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


class TflStopPoint(BaseModel):
    """Stop-point record returned by ``/StopPoint/{naptan_id}``.

    Used by the station resolver fallback when a NaPTAN code surfaced
    in a disruption payload is not present in the static dim_stations
    seed (e.g. bus stops, deprecated rail entries). Only the two fields
    the resolver needs are typed; the rest of the payload is ignored.
    """

    model_config = _tfl_model_config()

    naptan_id: str
    common_name: str


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


class TflJourneyMode(BaseModel):
    """Transport mode nested inside a journey leg (``leg.mode``)."""

    model_config = _tfl_model_config()

    name: str


class TflJourneyInstruction(BaseModel):
    """Human-readable instruction nested inside a journey leg."""

    model_config = _tfl_model_config()

    summary: str


class TflJourneyLeg(BaseModel):
    """Single leg of a planned journey returned by ``/Journey/JourneyResults``."""

    model_config = _tfl_model_config()

    duration: int
    mode: TflJourneyMode
    instruction: TflJourneyInstruction
    departure_time: datetime | None = None
    arrival_time: datetime | None = None


class TflJourneyResult(BaseModel):
    """One journey option from ``/Journey/JourneyResults`` ``journeys[]``."""

    model_config = _tfl_model_config()

    start_date_time: datetime
    arrival_date_time: datetime
    duration: int
    legs: list[TflJourneyLeg] = Field(default_factory=list)


class TflStopSearchMatch(BaseModel):
    """Single match from ``/StopPoint/Search/{query}`` ``matches[]``.

    ``id`` is the StopPoint/NaPTAN code used as an endpoint for journey
    planning and arrival queries.
    """

    model_config = _tfl_model_config()

    id: str
    name: str
    modes: list[str] = Field(default_factory=list)


class TflStopSearchResponse(BaseModel):
    """Top-level response from ``/StopPoint/Search/{query}``."""

    model_config = _tfl_model_config()

    matches: list[TflStopSearchMatch] = Field(default_factory=list)
