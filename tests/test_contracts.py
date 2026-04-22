"""Validate TfL API fixtures and exercise the Kafka event contracts.

Tier-1 TfL schemas validate the raw fixtures committed under
``tests/fixtures/``. Tier-2 Kafka event schemas are exercised via
hand-constructed roundtrips so the wire format stays honest even before
ingestion normalisation lands (TM-B*).

Fixtures are fetched once by ``scripts/fetch_tfl_samples.py`` (gated on
``TFL_APP_KEY``). If they are absent, the TfL tests skip with a pointer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from contracts.schemas import (
    ArrivalEvent,
    ArrivalPayload,
    DisruptionCategory,
    DisruptionEvent,
    DisruptionPayload,
    LineStatusEvent,
    LineStatusPayload,
    TflArrivalPrediction,
    TflDisruption,
    TflLineResponse,
    TransportMode,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load_or_skip(name: str) -> list[dict[str, object]]:
    path = FIXTURES / name
    if not path.exists():
        pytest.skip(
            f"fixture {name} not yet fetched — run `uv run python scripts/fetch_tfl_samples.py`"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list), f"expected a JSON array in {name}"
    return data


# ---------- Tier-1: raw TfL API fixtures ----------


def test_line_status_fixture_parses_as_tfl_line() -> None:
    for item in _load_or_skip("line_status_sample.json"):
        TflLineResponse.model_validate(item)


def test_arrivals_fixture_parses_as_tfl_prediction() -> None:
    for item in _load_or_skip("arrivals_sample.json"):
        TflArrivalPrediction.model_validate(item)


def test_disruptions_fixture_parses_as_tfl_disruption() -> None:
    for item in _load_or_skip("disruptions_sample.json"):
        TflDisruption.model_validate(item)


# ---------- Tier-2: internal Kafka event contracts ----------


def _now() -> datetime:
    return datetime.now(UTC)


def test_line_status_event_roundtrip() -> None:
    now = _now()
    payload = LineStatusPayload(
        line_id="victoria",
        line_name="Victoria",
        mode=TransportMode.TUBE,
        status_severity=10,
        status_severity_description="Good Service",
        reason=None,
        valid_from=now,
        valid_to=now + timedelta(hours=12),
    )
    event = LineStatusEvent(
        event_id=uuid4(),
        event_type="line-status.snapshot",
        ingested_at=now,
        payload=payload,
    )
    dumped = event.model_dump(mode="json")
    reloaded = LineStatusEvent.model_validate(dumped)
    assert reloaded == event
    assert LineStatusEvent.TOPIC_NAME == "line-status"


def test_arrival_event_roundtrip() -> None:
    now = _now()
    payload = ArrivalPayload(
        arrival_id="352100929",
        station_id="940GZZLUOXC",
        station_name="Oxford Circus Underground Station",
        line_id="bakerloo",
        platform_name="Northbound - Platform 4",
        direction="outbound",
        destination="Queen's Park Underground Station",
        expected_arrival=now + timedelta(seconds=225),
        time_to_station_seconds=225,
        vehicle_id="003",
    )
    event = ArrivalEvent(
        event_id=uuid4(),
        event_type="arrival.prediction",
        ingested_at=now,
        payload=payload,
    )
    reloaded = ArrivalEvent.model_validate(event.model_dump(mode="json"))
    assert reloaded == event
    assert ArrivalEvent.TOPIC_NAME == "arrivals"


def test_disruption_event_roundtrip() -> None:
    now = _now()
    payload = DisruptionPayload(
        disruption_id="2026-04-22-PIC-001",
        category=DisruptionCategory.REAL_TIME,
        category_description="Real Time",
        description="Signal failure at Acton Town.",
        summary="Severe delays on Piccadilly line",
        affected_routes=["piccadilly"],
        affected_stops=["940GZZLUATN"],
        closure_text="",
        severity=6,
        created=now - timedelta(hours=2),
        last_update=now,
    )
    event = DisruptionEvent(
        event_id=uuid4(),
        event_type="disruption.update",
        ingested_at=now,
        payload=payload,
    )
    reloaded = DisruptionEvent.model_validate(event.model_dump(mode="json"))
    assert reloaded == event
    assert DisruptionEvent.TOPIC_NAME == "disruptions"


def test_line_status_valid_window_enforced() -> None:
    now = _now()
    with pytest.raises(ValueError, match="valid_to"):
        LineStatusPayload(
            line_id="victoria",
            line_name="Victoria",
            mode=TransportMode.TUBE,
            status_severity=10,
            status_severity_description="Good Service",
            reason=None,
            valid_from=now,
            valid_to=now,
        )
