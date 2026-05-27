"""Behavioural tests for journey planning and stop search on :class:`TflClient`."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from contracts.schemas.tfl_api import TflJourneyResult, TflStopSearchResponse
from ingestion.tfl_client import TflClient


def _json_response(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client(transport: httpx.MockTransport, **kwargs: Any) -> TflClient:
    return TflClient(app_key="test-key", transport=transport, **kwargs)


async def test_search_stop_returns_tier1_response(
    stop_search_oxford_circus_fixture: dict[str, Any],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response(stop_search_oxford_circus_fixture)

    async with _client(make_transport(handler)) as client:
        result = await client.search_stop("oxford circus")

    assert captured[0].url.path.startswith("/StopPoint/Search/")
    assert isinstance(result, TflStopSearchResponse)
    assert result.matches[0].id == "940GZZLUOXC"


async def test_search_stop_url_encodes_reserved_characters(
    stop_search_oxford_circus_fixture: dict[str, Any],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response(stop_search_oxford_circus_fixture)

    async with _client(make_transport(handler)) as client:
        await client.search_stop("a/b c")

    # The reserved '/' must stay percent-encoded on the wire (raw_path)
    # so it cannot split the path into extra segments.
    assert captured[0].url.raw_path.split(b"?")[0] == b"/StopPoint/Search/a%2Fb%20c"


async def test_plan_journey_converts_tz_aware_time_to_london(
    journey_oxford_circus_to_bank_fixture: dict[str, Any],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response(journey_oxford_circus_to_bank_fixture)

    # 12:00 UTC on 1 Jul is 13:00 BST in London.
    async with _client(make_transport(handler)) as client:
        await client.plan_journey(
            "940GZZLUOXC",
            "940GZZLUBNK",
            departure_time=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        )

    params = captured[0].url.params
    assert params.get("date") == "20260701"
    assert params.get("time") == "1300"

    # A naive datetime is taken as already-London wall-clock, unchanged.
    captured.clear()
    async with _client(make_transport(handler)) as client:
        await client.plan_journey(
            "940GZZLUOXC",
            "940GZZLUBNK",
            departure_time=datetime(2026, 7, 1, 9, 5, tzinfo=ZoneInfo("Europe/London")).replace(
                tzinfo=None
            ),
        )
    assert captured[0].url.params.get("time") == "0905"


async def test_plan_journey_without_options_omits_time_and_mode(
    journey_oxford_circus_to_bank_fixture: dict[str, Any],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response(journey_oxford_circus_to_bank_fixture)

    async with _client(make_transport(handler)) as client:
        result = await client.plan_journey("940GZZLUOXC", "940GZZLUBNK")

    assert captured[0].url.path == "/Journey/JourneyResults/940GZZLUOXC/to/940GZZLUBNK"
    assert captured[0].url.params.get("date") is None
    assert captured[0].url.params.get("time") is None
    assert captured[0].url.params.get("mode") is None
    assert all(isinstance(item, TflJourneyResult) for item in result)
    assert len(result) == 2
    assert [leg.mode.name for leg in result[0].legs] == ["walking", "tube"]


async def test_plan_journey_with_departure_time_and_modes_sets_params(
    journey_oxford_circus_to_bank_fixture: dict[str, Any],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response(journey_oxford_circus_to_bank_fixture)

    async with _client(make_transport(handler)) as client:
        await client.plan_journey(
            "940GZZLUOXC",
            "940GZZLUBNK",
            departure_time=datetime(2026, 5, 27, 9, 5),
            modes=["tube", "bus"],
        )

    params = captured[0].url.params
    assert params.get("date") == "20260527"
    assert params.get("time") == "0905"
    assert params.get("timeIs") == "Departing"
    assert params.get("mode") == "tube,bus"
