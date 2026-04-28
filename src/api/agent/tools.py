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

from typing import Any, Literal

from langchain_core.tools import BaseTool, tool
from llama_index.core.retrievers import BaseRetriever
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


class TflDocSearchQuery(BaseModel):
    """Input schema for ``search_tfl_docs``."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=512)
    doc_id: Literal["tfl_business_plan", "mts_2018", "tfl_annual_report"] | None = None
    top_k: int = Field(default=5, ge=1, le=20)


def make_tools(
    *,
    pool: AsyncConnectionPool,
    retriever: dict[str, BaseRetriever],
) -> list[BaseTool]:
    """Build the five LangGraph tools bound to a pool + retriever map.

    Args:
        pool: Shared ``AsyncConnectionPool`` (TM-D2/D3 fetchers reuse it).
        retriever: Namespace → retriever map from ``build_retriever``.

    Returns:
        List of LangChain ``BaseTool`` instances ready for
        ``create_react_agent``.
    """

    @tool
    async def query_tube_status() -> list[dict[str, Any]]:
        """Return the current operational status of every line right now."""
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
        rows = await fetch_recent_disruptions(pool, limit=limit, mode=mode)
        return [r.model_dump(mode="json") for r in rows]

    @tool(args_schema=BusPunctualityQuery)
    async def query_bus_punctuality(stop_id: str) -> dict[str, Any] | str:
        """Return punctuality for a bus stop over the last 7 days.

        Caveat: this is a PROXY computed on top of TfL arrival
        predictions, not realised departure events. Cite the proxy
        nature when surfacing the percentages to the user.
        """
        result = await fetch_bus_punctuality(
            pool,
            stop_id=stop_id,
            window=BUS_PUNCTUALITY_WINDOW_DAYS,
        )
        if result is None:
            return f"No punctuality data for stop {stop_id!r}."
        return result.model_dump(mode="json")

    @tool(args_schema=TflDocSearchQuery)
    async def search_tfl_docs(
        query: str,
        doc_id: Literal["tfl_business_plan", "mts_2018", "tfl_annual_report"] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Return passages from TfL strategy docs ranked by relevance.

        Cite each hit by ``doc_title`` and ``page_start``. Use this tool
        for policy or forecast questions; reach for the SQL tools for
        live operational data.
        """
        snippets = await retrieve(retriever, query=query, doc_id=doc_id, top_k=top_k)
        return [s.model_dump(mode="json") for s in snippets]

    return [
        query_tube_status,
        query_line_reliability,
        query_recent_disruptions,
        query_bus_punctuality,
        search_tfl_docs,
    ]
