"""Unit tests for the journey-planning and arrivals agent tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from api.agent import tools as tools_module
from api.agent.tools import make_tools
from contracts.schemas.tfl_api import (
    TflArrivalPrediction,
    TflJourneyInstruction,
    TflJourneyLeg,
    TflJourneyMode,
    TflJourneyResult,
)


@dataclass
class FakeTflClient:
    """Stand-in exposing only the methods the journey/arrivals tools call."""

    journeys: list[TflJourneyResult] = field(default_factory=list)
    arrivals: list[TflArrivalPrediction] = field(default_factory=list)
    plan_calls: list[tuple[str, str]] = field(default_factory=list)
    arrival_calls: list[str] = field(default_factory=list)

    async def plan_journey(
        self,
        from_id: str,
        to_id: str,
        *,
        departure_time: datetime | None = None,
        modes: Any = None,
    ) -> list[TflJourneyResult]:
        self.plan_calls.append((from_id, to_id))
        return self.journeys

    async def fetch_arrivals(self, stop_id: str) -> list[TflArrivalPrediction]:
        self.arrival_calls.append(stop_id)
        return self.arrivals


def _leg(mode: str, summary: str, minutes: int) -> TflJourneyLeg:
    return TflJourneyLeg(
        duration=minutes,
        mode=TflJourneyMode(name=mode),
        instruction=TflJourneyInstruction(summary=summary),
    )


def _journey() -> TflJourneyResult:
    return TflJourneyResult(
        start_date_time=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
        arrival_date_time=datetime(2026, 5, 27, 9, 12, tzinfo=UTC),
        duration=12,
        legs=[_leg("walking", "Walk to Oxford Circus", 3), _leg("tube", "Central line to Bank", 9)],
    )


def _arrival(platform: str, line: str, destination: str, seconds: int) -> TflArrivalPrediction:
    return TflArrivalPrediction(
        id=f"{line}-{seconds}",
        naptan_id="940GZZLUBNK",
        station_name="Bank Underground Station",
        line_id=line.lower(),
        line_name=line,
        platform_name=platform,
        destination_name=destination,
        expected_arrival=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
        time_to_station=seconds,
        mode_name="tube",
    )


def _stub_resolver(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, str | None]) -> None:
    async def fake_resolve_name(*, tfl_client: Any, query: str) -> str | None:
        return mapping.get(query.strip().lower())

    monkeypatch.setattr(tools_module, "resolve_name", fake_resolve_name)


def _tool(tfl_client: Any, name: str) -> Any:
    tools = make_tools(pool=object(), tfl_client=tfl_client)  # type: ignore[arg-type]
    return next(t for t in tools if t.name == name)


def test_make_tools_omits_tfl_tools_without_client() -> None:
    names = [t.name for t in make_tools(pool=object())]  # type: ignore[arg-type]
    assert "plan_journey_tool" not in names
    assert "get_arrivals_tool" not in names


def test_make_tools_includes_tfl_tools_with_client() -> None:
    client = FakeTflClient()
    names = [t.name for t in make_tools(pool=object(), tfl_client=client)]  # type: ignore[arg-type]
    assert "plan_journey_tool" in names
    assert "get_arrivals_tool" in names


@pytest.mark.asyncio
async def test_plan_journey_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolver(
        monkeypatch,
        {"oxford circus": "940GZZLUOXC", "bank": "940GZZLUBNK"},
    )
    client = FakeTflClient(journeys=[_journey()])
    tool = _tool(client, "plan_journey_tool")

    result = await tool.ainvoke({"origin": "Oxford Circus", "destination": "Bank"})

    assert client.plan_calls == [("940GZZLUOXC", "940GZZLUBNK")]
    assert result["total_minutes"] == 12
    assert [leg["mode"] for leg in result["legs"]] == ["walking", "tube"]
    assert result["legs"][1]["summary"] == "Central line to Bank"


@pytest.mark.asyncio
async def test_plan_journey_unresolved_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolver(monkeypatch, {"bank": "940GZZLUBNK"})
    client = FakeTflClient(journeys=[_journey()])
    tool = _tool(client, "plan_journey_tool")

    result = await tool.ainvoke({"origin": "Nowhere", "destination": "Bank"})

    assert isinstance(result, str)
    assert "Nowhere" in result
    assert client.plan_calls == []


@pytest.mark.asyncio
async def test_plan_journey_rejects_unparseable_departure_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_resolver(
        monkeypatch,
        {"oxford circus": "940GZZLUOXC", "bank": "940GZZLUBNK"},
    )
    client = FakeTflClient(journeys=[_journey()])
    tool = _tool(client, "plan_journey_tool")

    result = await tool.ainvoke(
        {"origin": "Oxford Circus", "destination": "Bank", "departure_time": "tomorrow 9am"}
    )

    assert isinstance(result, str)
    assert "tomorrow 9am" in result
    assert client.plan_calls == []  # never plans "now" on a bad time


@pytest.mark.asyncio
async def test_plan_journey_unresolved_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolver(monkeypatch, {"oxford circus": "940GZZLUOXC"})
    client = FakeTflClient(journeys=[_journey()])
    tool = _tool(client, "plan_journey_tool")

    result = await tool.ainvoke({"origin": "Oxford Circus", "destination": "Atlantis"})

    assert isinstance(result, str)
    assert "Atlantis" in result
    assert client.plan_calls == []


@pytest.mark.asyncio
async def test_get_arrivals_groups_sorts_and_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolver(monkeypatch, {"bank": "940GZZLUBNK"})
    northbound = [
        _arrival("Northbound - Platform 1", "Central", "Epping", s)
        for s in (600, 60, 300, 480, 180, 720)
    ]
    southbound = [_arrival("Southbound - Platform 2", "Central", "Ealing", 240)]
    client = FakeTflClient(arrivals=[*northbound, *southbound])
    tool = _tool(client, "get_arrivals_tool")

    result = await tool.ainvoke({"stop": "Bank"})

    assert client.arrival_calls == ["940GZZLUBNK"]
    assert result["station"] == "Bank Underground Station"
    platforms = {p["platform"]: p for p in result["platforms"]}
    north = platforms["Northbound - Platform 1"]
    assert len(north["arrivals"]) == 5  # capped per platform
    assert [a["seconds"] for a in north["arrivals"]] == [60, 180, 300, 480, 600]  # sorted ascending
    assert platforms["Southbound - Platform 2"]["arrivals"][0]["destination"] == "Ealing"


@pytest.mark.asyncio
async def test_get_arrivals_unresolved_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolver(monkeypatch, {})
    client = FakeTflClient(arrivals=[_arrival("P1", "Central", "Epping", 60)])
    tool = _tool(client, "get_arrivals_tool")

    result = await tool.ainvoke({"stop": "Mordor"})

    assert isinstance(result, str)
    assert "Mordor" in result
    assert client.arrival_calls == []
