"""LangChain tools wrapping the TM-D2/D3 fetchers and the RAG retriever.

Five tools are exposed to the agent:

- ``query_tube_status`` — current operational status per line.
- ``query_line_reliability`` — reliability for one line over a window.
- ``query_recent_disruptions`` — most recent disruptions.
- ``query_bus_punctuality`` — bus-stop punctuality proxy.
- ``search_tfl_docs`` — RAG over the TfL strategy corpus.

Inputs are Pydantic models with ``extra="forbid"`` so the LLM cannot
smuggle unknown fields past the type system.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

import logfire
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ConfigDict, Field

from api.agent.extraction import normalise_line_id
from api.agent.rag import retrieve
from api.db import (
    BUS_PUNCTUALITY_WINDOW_DAYS,
    fetch_bus_punctuality,
    fetch_live_status,
    fetch_recent_disruptions,
    fetch_reliability,
)
from api.schemas import Mode
from api.stations import resolve_name

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from llama_index.core import VectorStoreIndex

    from ingestion.tfl_client.client import TflClient

_MAX_ARRIVALS_PER_PLATFORM = 5


class LineReliabilityQuery(BaseModel):
    """Input schema for ``query_line_reliability``."""

    model_config = ConfigDict(extra="forbid")

    line_id: str = Field(min_length=1, max_length=64)
    window_days: int = Field(default=7, ge=1, le=90)


class RecentDisruptionsQuery(BaseModel):
    """Input schema for ``query_recent_disruptions``."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=200)
    mode: Mode | None = None


class BusPunctualityQuery(BaseModel):
    """Input schema for ``query_bus_punctuality``."""

    model_config = ConfigDict(extra="forbid")

    stop_id: str = Field(min_length=1, max_length=64)


DocId = Literal[
    "business_plan_2026",
    "mts_delivery_2024_25",
    "bus_action_plan",
    "vision_zero",
    "cycling_action_plan",
    "travel_in_london_2025",
]


class TflDocSearchQuery(BaseModel):
    """Input schema for ``search_tfl_docs``."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=512)
    doc_id: DocId | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class PlanJourneyQuery(BaseModel):
    """Input schema for ``plan_journey_tool``."""

    model_config = ConfigDict(extra="forbid")

    origin: str = Field(min_length=1, max_length=128)
    destination: str = Field(min_length=1, max_length=128)
    departure_time: str | None = None


class GetArrivalsQuery(BaseModel):
    """Input schema for ``get_arrivals_tool``."""

    model_config = ConfigDict(extra="forbid")

    stop: str = Field(min_length=1, max_length=128)


def _parse_departure_time(value: str | None) -> datetime | None:
    """Parse an ISO-8601 departure time, returning ``None`` on bad input."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def make_tools(
    *,
    pool: AsyncConnectionPool,
    tfl_client: TflClient | None = None,
    retriever: VectorStoreIndex | None = None,
) -> list[BaseTool]:
    """Build the LangGraph tools bound to a pool (+ optional dependencies).

    Args:
        pool: Shared ``AsyncConnectionPool`` (TM-D2/D3 fetchers reuse it).
        tfl_client: Optional ``TflClient``. When ``None`` the journey and
            arrivals tools are omitted, since both call the live TfL API.
        retriever: pgvector index from ``build_retriever``. When ``None``
            the RAG tool is omitted and only the SQL tools are exposed, so
            the agent still serves live operational data.

    Returns:
        List of LangChain ``BaseTool`` instances ready for
        ``create_react_agent``: four SQL tools, plus the journey/arrivals
        tools when a ``TflClient`` is supplied and ``search_tfl_docs`` when
        a retriever is supplied.
    """
    from langchain_core.tools import tool  # noqa: PLC0415

    @tool
    async def query_tube_status() -> list[dict[str, Any]]:
        """Return the current operational status of every line right now."""
        with logfire.span("agent.tool.query_tube_status"):
            rows = await fetch_live_status(pool)
            return [r.model_dump(mode="json") for r in rows]

    @tool(args_schema=LineReliabilityQuery)
    async def query_line_reliability(
        line_id: str,
        window_days: int = 7,
    ) -> dict[str, Any] | str:
        """Return reliability for a single line over a window (default 7 days).

        ``line_id`` is normalised through a Pydantic AI Haiku call before
        the SQL fires, so free-text references like ``"Lizzy"`` map to
        the canonical ``elizabeth``.
        """
        with logfire.span(
            "agent.tool.query_line_reliability",
            line_id_raw=line_id,
            window_days=window_days,
        ):
            canonical = await normalise_line_id(line_id)
            if canonical is None:
                return f"Unknown line: {line_id!r}"
            result = await fetch_reliability(pool, line_id=canonical, window=window_days)
            if result is None:
                return f"No reliability data for {canonical}."
            return result.model_dump(mode="json")

    @tool(args_schema=RecentDisruptionsQuery)
    async def query_recent_disruptions(
        limit: int = 10,
        mode: Mode | None = None,
    ) -> list[dict[str, Any]]:
        """Return the most recent disruptions, optionally scoped by mode."""
        with logfire.span("agent.tool.query_recent_disruptions", limit=limit, mode=mode):
            rows = await fetch_recent_disruptions(pool, limit=limit, mode=mode)
            return [r.model_dump(mode="json") for r in rows]

    @tool(args_schema=BusPunctualityQuery)
    async def query_bus_punctuality(stop_id: str) -> dict[str, Any] | str:
        """Return punctuality for a bus stop over the last 7 days.

        Caveat: this is a PROXY computed on top of TfL arrival
        predictions, not realised departure events. Cite the proxy
        nature when surfacing the percentages to the user.
        """
        with logfire.span("agent.tool.query_bus_punctuality", stop_id=stop_id):
            result = await fetch_bus_punctuality(
                pool,
                stop_id=stop_id,
                window=BUS_PUNCTUALITY_WINDOW_DAYS,
            )
            if result is None:
                return f"No punctuality data for stop {stop_id!r}."
            return result.model_dump(mode="json")

    tools: list[BaseTool] = [
        query_tube_status,
        query_line_reliability,
        query_recent_disruptions,
        query_bus_punctuality,
    ]

    if tfl_client is not None:

        @tool(args_schema=PlanJourneyQuery)
        async def plan_journey_tool(
            origin: str,
            destination: str,
            departure_time: str | None = None,
        ) -> dict[str, Any] | str:
            """Plan a route between two stations (names or NaPTAN codes).

            Use when the user asks how to get from A to B. ``departure_time``
            is an optional ISO-8601 timestamp; omit it for "leave now".
            Returns the best option's total duration and per-leg breakdown.
            """
            with logfire.span(
                "agent.tool.plan_journey_tool",
                origin=origin,
                destination=destination,
            ):
                origin_id = await resolve_name(tfl_client=tfl_client, query=origin)
                if origin_id is None:
                    return f"Couldn't find station '{origin}'."
                destination_id = await resolve_name(tfl_client=tfl_client, query=destination)
                if destination_id is None:
                    return f"Couldn't find station '{destination}'."
                parsed_departure = _parse_departure_time(departure_time)
                if departure_time and parsed_departure is None:
                    return (
                        f"Couldn't understand the departure time '{departure_time}'. "
                        "Use an ISO time like 2026-05-27T09:00, or omit it to leave now."
                    )
                journeys = await tfl_client.plan_journey(
                    origin_id,
                    destination_id,
                    departure_time=parsed_departure,
                )
                if not journeys:
                    return f"No journeys found from '{origin}' to '{destination}'."
                best = journeys[0]
                return {
                    "total_minutes": best.duration,
                    "start": best.start_date_time.isoformat(),
                    "arrival": best.arrival_date_time.isoformat(),
                    "legs": [
                        {
                            "mode": leg.mode.name,
                            "summary": leg.instruction.summary,
                            "minutes": leg.duration,
                        }
                        for leg in best.legs
                    ],
                }

        @tool(args_schema=GetArrivalsQuery)
        async def get_arrivals_tool(stop: str) -> dict[str, Any] | str:
            """Return next arrivals at a stop, grouped by platform.

            Use for "when's the next train/bus at X". ``stop`` is a station
            name or NaPTAN code. Each platform lists up to five upcoming
            vehicles ordered by time to arrival.
            """
            with logfire.span("agent.tool.get_arrivals_tool", stop=stop):
                stop_id = await resolve_name(tfl_client=tfl_client, query=stop)
                if stop_id is None:
                    return f"Couldn't find stop '{stop}'."
                predictions = await tfl_client.fetch_arrivals(stop_id)
                if not predictions:
                    return f"No arrivals found for '{stop}'."
                grouped: dict[str, list[Any]] = {}
                for prediction in predictions:
                    grouped.setdefault(prediction.platform_name, []).append(prediction)
                platforms = [
                    {
                        "platform": platform,
                        "arrivals": [
                            {
                                "line": p.line_name,
                                "destination": p.destination_name,
                                "seconds": p.time_to_station,
                            }
                            for p in sorted(preds, key=lambda p: p.time_to_station)[
                                :_MAX_ARRIVALS_PER_PLATFORM
                            ]
                        ],
                    }
                    for platform, preds in sorted(grouped.items())
                ]
                return {"station": predictions[0].station_name, "platforms": platforms}

        tools.extend([plan_journey_tool, get_arrivals_tool])

    if retriever is not None:

        @tool(args_schema=TflDocSearchQuery)
        async def search_tfl_docs(
            query: str,
            doc_id: DocId | None = None,
            top_k: int = 5,
        ) -> list[dict[str, Any]]:
            """Return passages from TfL strategy docs ranked by relevance.

            Cite each hit by ``doc_title`` and ``page_start``. Use this tool
            for policy or forecast questions; reach for the SQL tools for
            live operational data.
            """
            with logfire.span(
                "agent.tool.search_tfl_docs",
                doc_id=doc_id,
                top_k=top_k,
                query_chars=len(query),
            ):
                snippets = await retrieve(retriever, query=query, doc_id=doc_id, top_k=top_k)
                return [s.model_dump(mode="json") for s in snippets]

        tools.append(search_tfl_docs)

    return tools
