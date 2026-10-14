"""Tests for the tier-1 disruption normaliser."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from contracts.schemas.common import DisruptionCategory
from contracts.schemas.disruptions import DisruptionPayload
from contracts.schemas.tfl_api import (
    TflArrivalPrediction,
    TflLineResponse,
)
from ingestion.tfl_client.normalise import disruption_payloads

_LINE_RESPONSE_ADAPTER = TypeAdapter(list[TflLineResponse])
_ARRIVAL_ADAPTER = TypeAdapter(list[TflArrivalPrediction])


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
    assert len({p.disruption_id for p in payloads}) == len(payloads), (
        "fixture's same-line dual disruptions must not collapse onto one id"
    )
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


def test_disruption_id_distinguishes_same_line_dual_disruptions() -> None:
    """Two disruptions on the same line sharing description/closure/category must
    not collapse onto one synthetic id when their affected stops differ.

    Matches the TfL-observed District-line case captured in the
    ``line_status_tube_detailed`` fixture.
    """
    base_disruption: dict[str, Any] = {
        "category": "RealTime",
        "categoryDescription": "RealTime",
        "description": "District Line: Severe delays. ",
        "closureText": "severeDelays",
        "affectedRoutes": [],
    }
    response = _LINE_RESPONSE_ADAPTER.validate_python(
        [
            {
                "id": "district",
                "name": "District",
                "modeName": "tube",
                "lineStatuses": [
                    {
                        "statusSeverity": 6,
                        "statusSeverityDescription": "Severe Delays",
                        "validityPeriods": [],
                        "disruption": {
                            **base_disruption,
                            "affectedStops": [
                                {"naptanId": "940GZZLUTNG"},
                                {"naptanId": "940GZZLURMD"},
                            ],
                        },
                    },
                    {
                        "statusSeverity": 6,
                        "statusSeverityDescription": "Severe Delays",
                        "validityPeriods": [],
                        "disruption": {
                            **base_disruption,
                            "affectedStops": [
                                {"naptanId": "940GZZLUEAB"},
                                {"naptanId": "940GZZLUACT"},
                            ],
                        },
                    },
                ],
            }
        ]
    )

    payloads = disruption_payloads(response)

    assert len(payloads) == 2
    assert payloads[0].disruption_id != payloads[1].disruption_id


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
