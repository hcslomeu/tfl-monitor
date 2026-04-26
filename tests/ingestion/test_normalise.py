"""Tests for tier-1 → tier-2 normalisation adapters."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from contracts.schemas.arrivals import ArrivalPayload
from contracts.schemas.common import DisruptionCategory, TransportMode
from contracts.schemas.disruptions import DisruptionPayload
from contracts.schemas.line_status import LineStatusPayload
from contracts.schemas.tfl_api import (
    TflArrivalPrediction,
    TflDisruption,
    TflLineResponse,
)
from ingestion.tfl_client.normalise import (
    arrival_payloads,
    disruption_payloads,
    line_status_payloads,
)

_LINE_RESPONSE_ADAPTER = TypeAdapter(list[TflLineResponse])
_ARRIVAL_ADAPTER = TypeAdapter(list[TflArrivalPrediction])
_DISRUPTION_ADAPTER = TypeAdapter(list[TflDisruption])


def test_line_status_payloads_from_multi_mode_fixture(
    line_status_multi_mode_fixture: list[dict[str, Any]],
) -> None:
    response = _LINE_RESPONSE_ADAPTER.validate_python(line_status_multi_mode_fixture)

    payloads = line_status_payloads(response)

    assert payloads, "expected at least one payload"
    assert all(isinstance(p, LineStatusPayload) for p in payloads)
    expected = sum(
        max(len(status.validity_periods), 1) for line in response for status in line.line_statuses
    )
    assert len(payloads) == expected
    assert {p.mode for p in payloads} <= set(TransportMode)
    sample = payloads[0]
    LineStatusPayload.model_validate(sample.model_dump())


def test_line_status_payloads_default_validity_when_missing() -> None:
    response = _LINE_RESPONSE_ADAPTER.validate_python(
        [
            {
                "id": "victoria",
                "name": "Victoria",
                "modeName": "tube",
                "lineStatuses": [
                    {
                        "statusSeverity": 10,
                        "statusSeverityDescription": "Good Service",
                        "validityPeriods": [],
                    }
                ],
            }
        ]
    )

    payloads = line_status_payloads(response)

    assert len(payloads) == 1
    assert (payloads[0].valid_to - payloads[0].valid_from).total_seconds() > 0


def test_arrival_payloads_from_oxford_circus_fixture(
    arrivals_oxford_circus_fixture: list[dict[str, Any]],
) -> None:
    response = _ARRIVAL_ADAPTER.validate_python(arrivals_oxford_circus_fixture)

    payloads = arrival_payloads(response)

    assert len(payloads) == len(response)
    assert all(isinstance(p, ArrivalPayload) for p in payloads)
    sample = payloads[0]
    assert sample.station_id == response[0].naptan_id
    assert sample.expected_arrival == response[0].expected_arrival
    ArrivalPayload.model_validate(sample.model_dump())


def test_arrival_payloads_handles_missing_optional_strings() -> None:
    response = _ARRIVAL_ADAPTER.validate_python(
        [
            {
                "id": "abc",
                "naptanId": "940GZZLUOXC",
                "stationName": "Oxford Circus",
                "lineId": "bakerloo",
                "lineName": "Bakerloo",
                "platformName": "Northbound - Platform 1",
                "expectedArrival": "2026-04-22T11:22:53Z",
                "timeToStation": 60,
                "modeName": "tube",
            }
        ]
    )

    payloads = arrival_payloads(response)

    assert payloads[0].direction == ""
    assert payloads[0].destination == ""


def test_disruption_payloads_from_tube_fixture(
    disruptions_tube_fixture: list[dict[str, Any]],
) -> None:
    response = _DISRUPTION_ADAPTER.validate_python(disruptions_tube_fixture)

    payloads = disruption_payloads(response)

    assert len(payloads) == len(response)
    assert all(isinstance(p, DisruptionPayload) for p in payloads)
    for payload in payloads:
        assert len(payload.disruption_id) == 32
        assert all(c in "0123456789abcdef" for c in payload.disruption_id)
        assert len(payload.summary) <= 160
        assert payload.severity == 0
        assert payload.category in set(DisruptionCategory)
    sample = payloads[0]
    DisruptionPayload.model_validate(sample.model_dump())


def test_disruption_id_is_stable_across_calls(
    disruptions_tube_fixture: list[dict[str, Any]],
) -> None:
    response = _DISRUPTION_ADAPTER.validate_python(disruptions_tube_fixture)

    first = [p.disruption_id for p in disruption_payloads(response)]
    second = [p.disruption_id for p in disruption_payloads(response)]

    assert first == second


def test_disruption_id_independent_of_route_order() -> None:
    base = {
        "category": "RealTime",
        "categoryDescription": "RealTime",
        "description": "Strike action.",
        "closureText": "severeDelays",
    }
    response_a = _DISRUPTION_ADAPTER.validate_python(
        [
            {
                **base,
                "affectedRoutes": [{"id": "victoria"}, {"id": "central"}],
                "affectedStops": [],
            }
        ]
    )
    response_b = _DISRUPTION_ADAPTER.validate_python(
        [
            {
                **base,
                "affectedRoutes": [{"id": "central"}, {"id": "victoria"}],
                "affectedStops": [],
            }
        ]
    )

    [payload_a] = disruption_payloads(response_a)
    [payload_b] = disruption_payloads(response_b)

    assert payload_a.disruption_id == payload_b.disruption_id


def test_disruption_unknown_category_falls_back_to_undefined() -> None:
    response = _DISRUPTION_ADAPTER.validate_python(
        [
            {
                "category": "NotAKnownCategory",
                "categoryDescription": "NotAKnownCategory",
                "description": "Mystery event.",
                "affectedRoutes": [],
                "affectedStops": [],
                "closureText": "",
            }
        ]
    )

    [payload] = disruption_payloads(response)

    assert payload.category == DisruptionCategory.UNDEFINED
