"""FastAPI entrypoint for the tfl-monitor API.

Status, reliability, disruptions, bus, and chat endpoints query Postgres
via a shared ``AsyncConnectionPool`` opened by the lifespan. The chat
agent is compiled once in the lifespan and cached on
``app.state.agent``. The shape of the API is fixed by
``contracts/openapi.yaml``.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Annotated, Any

import logfire
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sse_starlette.sse import EventSourceResponse

from api.agent.graph import compile_agent
from api.agent.history import append_message, fetch_history
from api.agent.streaming import frame_end, project, serialise
from api.db import (
    BUS_PUNCTUALITY_WINDOW_DAYS,
    build_pool,
    fetch_bus_punctuality,
    fetch_live_status,
    fetch_recent_disruptions,
    fetch_reliability,
    fetch_status_history,
)
from api.observability import configure_observability
from api.schemas import (
    BusPunctualityResponse,
    ChatMessageResponse,
    ChatRequest,
    DisruptionResponse,
    LineReliabilityResponse,
    LineStatusResponse,
    Mode,
    Problem,
)

MAX_HISTORY_WINDOW = timedelta(days=30)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open and close the shared Postgres connection pool.

    Mirrors Logfire's ``if-token-present`` pattern: when ``DATABASE_URL``
    is unset the lifespan no-ops and ``app.state.db_pool`` stays ``None``.
    Handlers that need the pool must return ``503`` in that case so the
    smoke test (``/health``) keeps working without secrets.
    """
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        logfire.info(
            "api_start_without_db_pool",
            service="tfl-monitor-api",
            database_url_configured=False,
        )
        yield
        return

    pool = build_pool(dsn)
    await pool.open()
    app.state.db_pool = pool
    app.state.agent = compile_agent(pool=pool)
    logfire.info(
        "api_db_pool_opened",
        service="tfl-monitor-api",
        database_url_configured=True,
        pool_min_size=1,
        pool_max_size=4,
        chat_agent_configured=app.state.agent is not None,
    )
    if app.state.agent is None:
        logfire.info(
            "api_chat_agent_disabled_no_credentials",
            service="tfl-monitor-api",
        )
    try:
        yield
    finally:
        await pool.close()
        app.state.db_pool = None
        app.state.agent = None
        logfire.info("api_db_pool_closed", service="tfl-monitor-api")


app = FastAPI(
    title="tfl-monitor API",
    version="0.0.1",
    description="See contracts/openapi.yaml for the full spec.",
    lifespan=lifespan,
)

# Pre-seed so unit tests that build ``TestClient(app)`` outside an
# ``async with`` block (and therefore skip the lifespan) still see the
# attribute. Tests that need a live pool / agent monkeypatch these slots.
app.state.db_pool = None
app.state.agent = None

configure_observability(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://tfl-monitor.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    """Build an RFC 7807 ``application/problem+json`` response."""
    payload = Problem(type="about:blank", title=title, status=status, detail=detail)
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content=payload.model_dump(exclude_none=True),
    )


@app.get("/health", operation_id="get_health")
async def get_health() -> dict[str, Any]:
    """Liveness probe used by container orchestrators and uptime checks."""
    return {"status": "ok", "dependencies": {}}


@app.get(
    "/api/v1/status/live",
    operation_id="get_status_live",
    response_model=list[LineStatusResponse],
)
async def get_status_live(request: Request) -> list[LineStatusResponse] | Response:
    pool = request.app.state.db_pool
    if pool is None:
        return _problem(503, "Service Unavailable", "Database pool is not available")
    return await fetch_live_status(pool)


@app.get(
    "/api/v1/status/history",
    operation_id="get_status_history",
    response_model=list[LineStatusResponse],
)
async def get_status_history(
    request: Request,
    from_: Annotated[datetime, Query(alias="from")],
    to: Annotated[datetime, Query()],
    line_id: Annotated[str | None, Query()] = None,
) -> list[LineStatusResponse] | Response:
    if from_ >= to:
        return _problem(400, "Bad Request", "`from` must be strictly before `to`")
    if to - from_ > MAX_HISTORY_WINDOW:
        return _problem(400, "Bad Request", "Window exceeds the 30-day maximum")

    pool = request.app.state.db_pool
    if pool is None:
        return _problem(503, "Service Unavailable", "Database pool is not available")
    return await fetch_status_history(pool, from_dt=from_, to_dt=to, line_id=line_id)


@app.get(
    "/api/v1/reliability/{line_id}",
    operation_id="get_line_reliability",
    response_model=LineReliabilityResponse,
)
async def get_line_reliability(
    request: Request,
    line_id: str,
    window: Annotated[int, Query(ge=1, le=90)] = 7,
) -> LineReliabilityResponse | Response:
    pool = request.app.state.db_pool
    if pool is None:
        return _problem(503, "Service Unavailable", "Database pool is not available")

    result = await fetch_reliability(pool, line_id=line_id, window=window)
    if result is None:
        return _problem(
            404,
            "Not Found",
            f"No reliability data for line {line_id} in the last {window} days",
        )
    return result


@app.get(
    "/api/v1/disruptions/recent",
    operation_id="get_recent_disruptions",
    response_model=list[DisruptionResponse],
)
async def get_recent_disruptions(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    mode: Annotated[Mode | None, Query()] = None,
) -> list[DisruptionResponse] | Response:
    pool = request.app.state.db_pool
    if pool is None:
        return _problem(503, "Service Unavailable", "Database pool is not available")
    return await fetch_recent_disruptions(pool, limit=limit, mode=mode)


@app.get(
    "/api/v1/bus/{stop_id}/punctuality",
    operation_id="get_bus_punctuality",
    response_model=BusPunctualityResponse,
)
async def get_bus_punctuality(
    request: Request,
    stop_id: str,
) -> BusPunctualityResponse | Response:
    pool = request.app.state.db_pool
    if pool is None:
        return _problem(503, "Service Unavailable", "Database pool is not available")
    result = await fetch_bus_punctuality(pool, stop_id=stop_id, window=BUS_PUNCTUALITY_WINDOW_DAYS)
    if result is None:
        return _problem(
            404,
            "Not Found",
            f"No punctuality data for stop {stop_id}",
        )
    return result


@app.post("/api/v1/chat/stream", operation_id="post_chat_stream", response_model=None)
async def post_chat_stream(request: Request, body: ChatRequest) -> Response:
    """Stream a LangGraph agent response over Server-Sent Events.

    Persists the user turn before yielding the first frame and the
    assistant turn after the final ``end`` frame so a concurrent
    ``GET /history`` always sees a coherent view of the conversation.
    """
    pool = request.app.state.db_pool
    agent = getattr(request.app.state, "agent", None)
    if pool is None:
        return _problem(503, "Service Unavailable", "Database pool is not available")
    if agent is None:
        return _problem(503, "Service Unavailable", "Chat agent is not configured")

    await append_message(pool, thread_id=body.thread_id, role="user", content=body.message)

    async def event_stream() -> AsyncIterator[dict[str, str]]:
        config: dict[str, Any] = {"configurable": {"thread_id": body.thread_id}}
        inputs = {"messages": [{"role": "user", "content": body.message}]}
        assistant_buffer: list[str] = []
        try:
            async for mode, payload in agent.astream(
                inputs, config=config, stream_mode=["messages", "updates"]
            ):
                if await request.is_disconnected():
                    return
                for frame in project(mode, payload):
                    if frame["type"] == "token":
                        assistant_buffer.append(frame["content"])
                    yield {"data": serialise(frame)}
            yield {"data": serialise(frame_end())}
        except asyncio.CancelledError:
            raise
        except Exception:
            logfire.exception("chat_stream_failed", thread_id=body.thread_id)
            yield {"data": serialise(frame_end("error"))}
        finally:
            if assistant_buffer:
                await append_message(
                    pool,
                    thread_id=body.thread_id,
                    role="assistant",
                    content="".join(assistant_buffer),
                )

    return EventSourceResponse(event_stream(), ping=15)


@app.get(
    "/api/v1/chat/{thread_id}/history",
    operation_id="get_chat_history",
    response_model=list[ChatMessageResponse],
)
async def get_chat_history(
    request: Request,
    thread_id: str,
) -> list[ChatMessageResponse] | Response:
    pool = request.app.state.db_pool
    if pool is None:
        return _problem(503, "Service Unavailable", "Database pool is not available")
    rows = await fetch_history(pool, thread_id=thread_id)
    if not rows:
        return _problem(404, "Not Found", f"No history for thread {thread_id}")
    return rows
