"""Unit tests for the LangGraph SQL + RAG tools."""

from __future__ import annotations

from datetime import UTC
from typing import Any

import pytest
from pydantic import ValidationError

from api.agent import tools as tools_module
from api.agent.tools import (
    BusPunctualityQuery,
    LineReliabilityQuery,
    RecentDisruptionsQuery,
    TflDocSearchQuery,
    make_tools,
)
from api.schemas import (
    BusPunctualityResponse,
    DisruptionResponse,
    LineReliabilityResponse,
    LineStatusResponse,
)

# ---------- input schema validation ---------------------------------------


def test_line_reliability_query_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        LineReliabilityQuery(line_id="piccadilly", window_days=7, sneaky="x")  # type: ignore[call-arg]


def test_line_reliability_query_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        LineReliabilityQuery(line_id="piccadilly", window_days=0)
    with pytest.raises(ValidationError):
        LineReliabilityQuery(line_id="piccadilly", window_days=91)


def test_recent_disruptions_query_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        RecentDisruptionsQuery(limit=5, mode="tube", drop="table")  # type: ignore[call-arg]


def test_recent_disruptions_query_caps_limit() -> None:
    with pytest.raises(ValidationError):
        RecentDisruptionsQuery(limit=201)


def test_bus_punctuality_query_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        BusPunctualityQuery(stop_id="490000077E", window=99)  # type: ignore[call-arg]


def test_bus_punctuality_query_requires_stop_id() -> None:
    with pytest.raises(ValidationError):
        BusPunctualityQuery(stop_id="")


def test_doc_search_query_rejects_unknown_doc_id() -> None:
    with pytest.raises(ValidationError):
        TflDocSearchQuery(query="forecasts", doc_id="random_blog")  # type: ignore[arg-type]


def test_doc_search_query_caps_top_k() -> None:
    with pytest.raises(ValidationError):
        TflDocSearchQuery(query="forecasts", top_k=21)


# ---------- make_tools wiring ---------------------------------------------


def test_make_tools_returns_five_tools() -> None:
    tools = make_tools(pool=object(), retriever={})  # type: ignore[arg-type]
    names = [t.name for t in tools]
    assert names == [
        "query_tube_status",
        "query_line_reliability",
        "query_recent_disruptions",
        "query_bus_punctuality",
        "search_tfl_docs",
    ]


def test_bus_tool_docstring_cites_proxy_caveat() -> None:
    tools = make_tools(pool=object(), retriever={})  # type: ignore[arg-type]
    bus_tool = next(t for t in tools if t.name == "query_bus_punctuality")
    description = (bus_tool.description or "").lower()
    assert "proxy" in description


# ---------- happy-path forwarding -----------------------------------------


def _make_status() -> LineStatusResponse:
    from datetime import datetime

    return LineStatusResponse(
        line_id="piccadilly",
        line_name="Piccadilly",
        mode="tube",
        status_severity=10,
        status_severity_description="Good Service",
        reason=None,
        valid_from=datetime(2026, 4, 28, tzinfo=UTC),
        valid_to=datetime(2026, 4, 28, 23, 59, tzinfo=UTC),
    )


def _make_reliability() -> LineReliabilityResponse:
    return LineReliabilityResponse(
        line_id="piccadilly",
        line_name="Piccadilly",
        mode="tube",
        window_days=7,
        reliability_percent=99.0,
        sample_size=42,
        severity_histogram={"10": 41, "9": 1},
    )


def _make_disruption() -> DisruptionResponse:
    from datetime import datetime

    return DisruptionResponse(
        disruption_id="d1",
        category="RealTime",
        category_description="Realtime",
        description="signal failure",
        summary="signal failure on Piccadilly",
        affected_routes=["piccadilly"],
        affected_stops=[],
        closure_text="",
        severity=2,
        created=datetime(2026, 4, 28, tzinfo=UTC),
        last_update=datetime(2026, 4, 28, 12, tzinfo=UTC),
    )


def _make_bus() -> BusPunctualityResponse:
    return BusPunctualityResponse(
        stop_id="490000077E",
        stop_name="Aldwych",
        window_days=7,
        on_time_percent=80.0,
        early_percent=10.0,
        late_percent=10.0,
        sample_size=100,
    )


@pytest.mark.asyncio
async def test_query_tube_status_forwards(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    async def fake_fetch_live_status(pool: Any) -> list[LineStatusResponse]:
        calls.append(pool)
        return [_make_status()]

    monkeypatch.setattr(tools_module, "fetch_live_status", fake_fetch_live_status)

    pool = object()
    tools = make_tools(pool=pool, retriever={})  # type: ignore[arg-type]
    tube_tool = next(t for t in tools if t.name == "query_tube_status")

    result = await tube_tool.ainvoke({})

    assert calls == [pool]
    assert isinstance(result, list)
    assert result[0]["line_id"] == "piccadilly"


@pytest.mark.asyncio
async def test_query_line_reliability_normalises_then_fetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_normalise(text: str) -> str | None:
        captured["normalise"] = text
        return "elizabeth"

    async def fake_fetch_reliability(
        pool: Any, *, line_id: str, window: int
    ) -> LineReliabilityResponse:
        captured["fetch"] = {"line_id": line_id, "window": window}
        return _make_reliability()

    monkeypatch.setattr(tools_module, "normalise_line_id", fake_normalise)
    monkeypatch.setattr(tools_module, "fetch_reliability", fake_fetch_reliability)

    tools = make_tools(pool=object(), retriever={})  # type: ignore[arg-type]
    rel_tool = next(t for t in tools if t.name == "query_line_reliability")

    result = await rel_tool.ainvoke({"line_id": "Lizzy", "window_days": 14})

    assert captured["normalise"] == "Lizzy"
    assert captured["fetch"] == {"line_id": "elizabeth", "window": 14}
    assert isinstance(result, dict)
    assert result["line_id"] == "piccadilly"  # _make_reliability fixture id


@pytest.mark.asyncio
async def test_query_line_reliability_returns_string_when_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_normalise(_text: str) -> str | None:
        return None

    monkeypatch.setattr(tools_module, "normalise_line_id", fake_normalise)

    tools = make_tools(pool=object(), retriever={})  # type: ignore[arg-type]
    rel_tool = next(t for t in tools if t.name == "query_line_reliability")
    result = await rel_tool.ainvoke({"line_id": "moon-line"})
    assert isinstance(result, str)
    assert "Unknown line" in result


@pytest.mark.asyncio
async def test_query_recent_disruptions_forwards(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_fetch(pool: Any, *, limit: int, mode: Any) -> list[DisruptionResponse]:
        calls.append({"limit": limit, "mode": mode})
        return [_make_disruption()]

    monkeypatch.setattr(tools_module, "fetch_recent_disruptions", fake_fetch)

    tools = make_tools(pool=object(), retriever={})  # type: ignore[arg-type]
    disr_tool = next(t for t in tools if t.name == "query_recent_disruptions")
    result = await disr_tool.ainvoke({"limit": 5, "mode": "tube"})

    assert calls == [{"limit": 5, "mode": "tube"}]
    assert result[0]["disruption_id"] == "d1"


@pytest.mark.asyncio
async def test_query_bus_punctuality_forwards(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_fetch(pool: Any, *, stop_id: str, window: int) -> BusPunctualityResponse:
        calls.append({"stop_id": stop_id, "window": window})
        return _make_bus()

    monkeypatch.setattr(tools_module, "fetch_bus_punctuality", fake_fetch)

    tools = make_tools(pool=object(), retriever={})  # type: ignore[arg-type]
    bus_tool = next(t for t in tools if t.name == "query_bus_punctuality")
    result = await bus_tool.ainvoke({"stop_id": "490000077E"})

    assert calls == [{"stop_id": "490000077E", "window": 7}]
    assert result["stop_id"] == "490000077E"


@pytest.mark.asyncio
async def test_search_tfl_docs_delegates_to_retrieve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_retrieve(
        retrievers: dict[str, Any], *, query: str, doc_id: str | None, top_k: int
    ) -> list[Any]:
        captured["retrievers"] = retrievers
        captured["query"] = query
        captured["doc_id"] = doc_id
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr(tools_module, "retrieve", fake_retrieve)

    retriever_map = {"tfl_business_plan": object()}
    tools = make_tools(pool=object(), retriever=retriever_map)  # type: ignore[arg-type]
    docs_tool = next(t for t in tools if t.name == "search_tfl_docs")
    result = await docs_tool.ainvoke(
        {"query": "Bakerloo extension", "doc_id": "tfl_business_plan", "top_k": 3}
    )

    assert captured == {
        "retrievers": retriever_map,
        "query": "Bakerloo extension",
        "doc_id": "tfl_business_plan",
        "top_k": 3,
    }
    assert result == []
