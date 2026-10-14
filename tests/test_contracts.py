"""Validate the TfL API fixtures against the tier-1 contracts.

Tier-1 TfL schemas validate the raw fixtures committed under
``tests/fixtures/``.

Fixtures are fetched once by ``scripts/fetch_tfl_samples.py`` (gated on
``TFL_APP_KEY``). If they are absent, the TfL tests skip with a pointer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.schemas import TflArrivalPrediction, TflLineResponse
from contracts.schemas.tfl_api import (
    TflJourneyResult,
    TflStopPoint,
    TflStopSearchResponse,
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


def _load_tfl_object(name: str) -> dict[str, object]:
    data = json.loads((FIXTURES / "tfl" / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"expected a JSON object in {name}"
    return data


# ---------- Tier-1: raw TfL API fixtures ----------


def test_line_status_fixture_parses_as_tfl_line() -> None:
    for item in _load_or_skip("line_status_sample.json"):
        TflLineResponse.model_validate(item)


def test_arrivals_fixture_parses_as_tfl_prediction() -> None:
    for item in _load_or_skip("arrivals_sample.json"):
        TflArrivalPrediction.model_validate(item)


def test_journey_fixture_parses_with_nested_legs() -> None:
    payload = _load_tfl_object("journey_oxford_circus_to_bank.json")
    raw_journeys = payload["journeys"]
    assert isinstance(raw_journeys, list)
    journeys = [TflJourneyResult.model_validate(j) for j in raw_journeys]

    assert len(journeys) == 2
    first = journeys[0]
    assert first.duration == 12
    assert [leg.mode.name for leg in first.legs] == ["walking", "tube"]
    assert first.legs[1].instruction.summary == "Central line to Bank"
    assert first.legs[0].departure_time is not None


def test_stop_search_fixture_parses_matches() -> None:
    response = TflStopSearchResponse.model_validate(
        _load_tfl_object("stop_search_oxford_circus.json")
    )

    assert [match.id for match in response.matches] == ["940GZZLUOXC", "490G00251P"]
    assert response.matches[0].modes == ["tube"]


def test_hub_stop_point_fixture_parses_children_with_modes() -> None:
    hub = TflStopPoint.model_validate(_load_tfl_object("stop_point_hub_bank.json"))

    assert hub.naptan_id == "HUBBAN"
    assert {child.naptan_id for child in hub.children} == {
        "490G00007599",
        "940GZZDLBNK",
        "940GZZLUBNK",
    }
    tube_child = next(c for c in hub.children if "tube" in c.modes)
    assert tube_child.naptan_id == "940GZZLUBNK"
