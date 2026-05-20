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
    TflLineResponse,
)
from ingestion.tfl_client.normalise import (
    arrival_payloads,
    disruption_payloads,
    line_status_payloads,
)

_LINE_RESPONSE_ADAPTER = TypeAdapter(list[TflLineResponse])
_ARRIVAL_ADAPTER = TypeAdapter(list[TflArrivalPrediction])


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


def test_disruption_payloads_from_detailed_fixture(
    line_status_tube_detailed_fixture: list[dict[str, Any]],
) -> None:
    response = _LINE_RESPONSE_ADAPTER.validate_python(line_status_tube_detailed_fixture)

    payloads = disruption_payloads(response)

    expected = sum(
        1 for line in response for status in line.line_statuses if status.disruption is not None
    )
    assert len(payloads) == expected > 0
    assert all(isinstance(p, DisruptionPayload) for p in payloads)
    for payload in payloads:
        assert len(payload.disruption_id) == 32
        assert all(c in "0123456789abcdef" for c in payload.disruption_id)
        assert len(payload.summary) <= 160
        assert payload.severity == 0
        assert payload.category in set(DisruptionCategory)
        assert len(payload.affected_routes) == 1
        assert payload.affected_routes[0]
    sample = payloads[0]
    DisruptionPayload.model_validate(sample.model_dump())


def test_disruption_payloads_skip_line_statuses_without_disruption() -> None:
    response = _LINE_RESPONSE_ADAPTER.validate_python(
        [
            {
                "id": "central",
                "name": "Central",
                "modeName": "tube",
                "lineStatuses": [
                    {
                        "statusSeverity": 10,
                        "statusSeverityDescription": "Good Service",
                        "validityPeriods": [],
                        "disruption": None,
                    }
                ],
            }
        ]
    )

    assert disruption_payloads(response) == []


def test_disruption_payloads_set_affected_routes_to_parent_line_id(
    line_status_tube_detailed_fixture: list[dict[str, Any]],
) -> None:
    response = _LINE_RESPONSE_ADAPTER.validate_python(line_status_tube_detailed_fixture)

    payloads = disruption_payloads(response)

    pairs = []
    for line in response:
        for status in line.line_statuses:
            if status.disruption is not None:
                pairs.append(line.id)
    assert [p.affected_routes[0] for p in payloads] == pairs


def test_disruption_payloads_extract_affected_stops_from_naptan_ids(
    line_status_tube_detailed_fixture: list[dict[str, Any]],
) -> None:
    response = _LINE_RESPONSE_ADAPTER.validate_python(line_status_tube_detailed_fixture)

    payloads = disruption_payloads(response)

    populated = [p for p in payloads if p.affected_stops]
    assert populated, "expected at least one disruption with affected stops"
    for payload in populated:
        assert all(stop.startswith("940") for stop in payload.affected_stops)
        assert len(set(payload.affected_stops)) == len(payload.affected_stops)


def test_disruption_id_is_stable_across_calls(
    line_status_tube_detailed_fixture: list[dict[str, Any]],
) -> None:
    response = _LINE_RESPONSE_ADAPTER.validate_python(line_status_tube_detailed_fixture)

    first = [p.disruption_id for p in disruption_payloads(response)]
    second = [p.disruption_id for p in disruption_payloads(response)]

    assert first == second


def test_disruption_id_distinguishes_disruptions_across_lines() -> None:
    base_disruption = {
        "category": "RealTime",
        "categoryDescription": "RealTime",
        "description": "Severe delays.",
        "closureText": "severeDelays",
        "affectedRoutes": [],
        "affectedStops": [],
    }
    response = _LINE_RESPONSE_ADAPTER.validate_python(
        [
            {
                "id": "victoria",
                "name": "Victoria",
                "modeName": "tube",
                "lineStatuses": [
                    {
                        "statusSeverity": 6,
                        "statusSeverityDescription": "Severe Delays",
                        "validityPeriods": [],
                        "disruption": base_disruption,
                    }
                ],
            },
            {
                "id": "central",
                "name": "Central",
                "modeName": "tube",
                "lineStatuses": [
                    {
                        "statusSeverity": 6,
                        "statusSeverityDescription": "Severe Delays",
                        "validityPeriods": [],
                        "disruption": base_disruption,
                    }
                ],
            },
        ]
    )

    payloads = disruption_payloads(response)

    assert len(payloads) == 2
    assert payloads[0].disruption_id != payloads[1].disruption_id


def test_disruption_unknown_category_falls_back_to_undefined() -> None:
    response = _LINE_RESPONSE_ADAPTER.validate_python(
        [
            {
                "id": "victoria",
                "name": "Victoria",
                "modeName": "tube",
                "lineStatuses": [
                    {
                        "statusSeverity": 6,
                        "statusSeverityDescription": "Severe Delays",
                        "validityPeriods": [],
                        "disruption": {
                            "category": "NotAKnownCategory",
                            "categoryDescription": "NotAKnownCategory",
                            "description": "Mystery event.",
                            "affectedRoutes": [],
                            "affectedStops": [],
                            "closureText": "",
                        },
                    }
                ],
            }
        ]
    )

    [payload] = disruption_payloads(response)

    assert payload.category == DisruptionCategory.UNDEFINED


def test_disruption_id_ignores_trailing_whitespace_in_description() -> None:
    def _wrap(description: str) -> list[dict[str, Any]]:
        return [
            {
                "id": "victoria",
                "name": "Victoria",
                "modeName": "tube",
                "lineStatuses": [
                    {
                        "statusSeverity": 6,
                        "statusSeverityDescription": "Severe Delays",
                        "validityPeriods": [],
                        "disruption": {
                            "category": "RealTime",
                            "categoryDescription": "RealTime",
                            "description": description,
                            "affectedRoutes": [],
                            "affectedStops": [],
                            "closureText": "",
                        },
                    }
                ],
            }
        ]

    clean_response = _LINE_RESPONSE_ADAPTER.validate_python(_wrap("Severe delays on Victoria."))
    padded_response = _LINE_RESPONSE_ADAPTER.validate_python(
        _wrap("  Severe delays on Victoria.  \n")
    )

    [clean] = disruption_payloads(clean_response)
    [padded] = disruption_payloads(padded_response)

    assert clean.disruption_id == padded.disruption_id


def test_disruption_affected_stops_dedupes_repeated_naptan_ids() -> None:
    response = _LINE_RESPONSE_ADAPTER.validate_python(
        [
            {
                "id": "victoria",
                "name": "Victoria",
                "modeName": "tube",
                "lineStatuses": [
                    {
                        "statusSeverity": 6,
                        "statusSeverityDescription": "Severe Delays",
                        "validityPeriods": [],
                        "disruption": {
                            "category": "RealTime",
                            "categoryDescription": "RealTime",
                            "description": "Engineering works.",
                            "affectedRoutes": [],
                            "affectedStops": [
                                {"naptanId": "940GZZLUVIC"},
                                {"naptanId": "940GZZLUVIC"},
                                {"naptanId": "940GZZLUKSX"},
                                {"naptanId": "940GZZLUVIC"},
                            ],
                            "closureText": "",
                        },
                    }
                ],
            }
        ]
    )

    [payload] = disruption_payloads(response)

    assert payload.affected_stops == ["940GZZLUVIC", "940GZZLUKSX"]


def test_line_status_skips_unknown_transport_mode() -> None:
    response = _LINE_RESPONSE_ADAPTER.validate_python(
        [
            {
                "id": "alien-line",
                "name": "Alien Line",
                "modeName": "hyperloop",
                "lineStatuses": [
                    {
                        "statusSeverity": 10,
                        "statusSeverityDescription": "Good Service",
                        "validityPeriods": [],
                    }
                ],
            },
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
            },
        ]
    )

    payloads = line_status_payloads(response)

    assert len(payloads) == 1
    assert payloads[0].line_id == "victoria"


def test_line_status_default_validity_shared_across_payloads() -> None:
    response = _LINE_RESPONSE_ADAPTER.validate_python(
        [
            {
                "id": f"line-{idx}",
                "name": f"Line {idx}",
                "modeName": "tube",
                "lineStatuses": [
                    {
                        "statusSeverity": 10,
                        "statusSeverityDescription": "Good Service",
                        "validityPeriods": [],
                    }
                ],
            }
            for idx in range(5)
        ]
    )

    payloads = line_status_payloads(response)

    assert len(payloads) == 5
    valid_from_values = {p.valid_from for p in payloads}
    valid_to_values = {p.valid_to for p in payloads}
    assert len(valid_from_values) == 1, "default valid_from must be captured once per call"
    assert len(valid_to_values) == 1, "default valid_to must be captured once per call"
