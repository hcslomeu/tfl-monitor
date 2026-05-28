"""Unit tests for the live TfL agent tools + the RAG tool."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from api.agent import tools as tools_module
from api.agent.tools import RecentDisruptionsQuery, TflDocSearchQuery, make_tools
from api.schemas import DisruptionResponse, LineStatusResponse

# ---------- input schema validation ---------------------------------------


def test_recent_disruptions_query_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        RecentDisruptionsQuery(limit=5, mode="tube", drop="table")  # type: ignore[call-arg]


def test_recent_disruptions_query_caps_limit() -> None:
    with pytest.raises(ValidationError):
        RecentDisruptionsQuery(limit=201)


def test_doc_search_query_rejects_unknown_doc_id() -> None:
    with pytest.raises(ValidationError):
        TflDocSearchQuery(query="forecasts", doc_id="random_blog")  # type: ignore[arg-type]


def test_doc_search_query_caps_top_k() -> None:
    with pytest.raises(ValidationError):
        TflDocSearchQuery(query="forecasts", top_k=21)


# ---------- make_tools wiring ---------------------------------------------


def test_make_tools_with_tfl_client_and_retriever() -> None:
    tools = make_tools(pool=object(), tfl_client=object(), retriever={})  # type: ignore[arg-type]
    names = [t.name for t in tools]
    assert names == [
        "query_tube_status",
        "query_recent_disruptions",
        "plan_journey_tool",
        "get_arrivals_tool",
        "search_tfl_docs",
    ]


def test_make_tools_without_tfl_client_omits_live_tools() -> None:
    tools = make_tools(pool=object(), retriever={})  # type: ignore[arg-type]
    assert [t.name for t in tools] == ["search_tfl_docs"]


# ---------- happy-path forwarding -----------------------------------------


def _make_status() -> LineStatusResponse:
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


def _make_disruption() -> DisruptionResponse:
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


@pytest.mark.asyncio
async def test_query_tube_status_forwards(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    async def fake_fetch_live_status(tfl_client: Any) -> list[LineStatusResponse]:
        calls.append(tfl_client)
        return [_make_status()]

    monkeypatch.setattr(tools_module, "fetch_live_status", fake_fetch_live_status)

    tfl_client = object()
    tools = make_tools(pool=object(), tfl_client=tfl_client)  # type: ignore[arg-type]
    tube_tool = next(t for t in tools if t.name == "query_tube_status")

    result = await tube_tool.ainvoke({})

    assert calls == [tfl_client]
    assert isinstance(result, list)
    assert result[0]["line_id"] == "piccadilly"


@pytest.mark.asyncio
async def test_query_tube_status_returns_friendly_string_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(_tfl_client: Any) -> list[LineStatusResponse]:
        raise RuntimeError("TfL down")

    monkeypatch.setattr(tools_module, "fetch_live_status", boom)

    tools = make_tools(pool=object(), tfl_client=object())  # type: ignore[arg-type]
    tube_tool = next(t for t in tools if t.name == "query_tube_status")

    result = await tube_tool.ainvoke({})

    assert isinstance(result, str)
    assert "couldn't fetch live line status" in result.lower()


@pytest.mark.asyncio
async def test_query_recent_disruptions_forwards(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_fetch(
        tfl_client: Any, *, pool: Any, limit: int, mode: Any
    ) -> list[DisruptionResponse]:
        calls.append({"tfl_client": tfl_client, "pool": pool, "limit": limit, "mode": mode})
        return [_make_disruption()]

    monkeypatch.setattr(tools_module, "fetch_recent_disruptions", fake_fetch)

    tfl_client = object()
    pool = object()
    tools = make_tools(pool=pool, tfl_client=tfl_client)  # type: ignore[arg-type]
    disr_tool = next(t for t in tools if t.name == "query_recent_disruptions")

    result = await disr_tool.ainvoke({"limit": 5, "mode": "tube"})

    assert calls == [{"tfl_client": tfl_client, "pool": pool, "limit": 5, "mode": "tube"}]
    assert result[0]["disruption_id"] == "d1"


@pytest.mark.asyncio
async def test_query_recent_disruptions_returns_friendly_string_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*_args: Any, **_kwargs: Any) -> list[DisruptionResponse]:
        raise RuntimeError("TfL down")

    monkeypatch.setattr(tools_module, "fetch_recent_disruptions", boom)

    tools = make_tools(pool=object(), tfl_client=object())  # type: ignore[arg-type]
    disr_tool = next(t for t in tools if t.name == "query_recent_disruptions")

    result = await disr_tool.ainvoke({})

    assert isinstance(result, str)
    assert "couldn't fetch recent disruptions" in result.lower()


@pytest.mark.asyncio
async def test_search_tfl_docs_delegates_to_retrieve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_retrieve(index: Any, *, query: str, doc_id: str | None, top_k: int) -> list[Any]:
        captured["index"] = index
        captured["query"] = query
        captured["doc_id"] = doc_id
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr(tools_module, "retrieve", fake_retrieve)

    retriever = object()
    tools = make_tools(pool=object(), retriever=retriever)  # type: ignore[arg-type]
    docs_tool = next(t for t in tools if t.name == "search_tfl_docs")
    result = await docs_tool.ainvoke(
        {"query": "Bakerloo extension", "doc_id": "business_plan_2026", "top_k": 3}
    )

    assert captured == {
        "index": retriever,
        "query": "Bakerloo extension",
        "doc_id": "business_plan_2026",
        "top_k": 3,
    }
    assert result == []
