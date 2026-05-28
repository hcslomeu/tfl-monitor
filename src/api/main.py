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
from typing import Annotated, Any

import logfire
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sse_starlette.sse import EventSourceResponse

from api.agent.history import append_message, fetch_history
from api.agent.streaming import frame_end, project, serialise
from api.db import build_pool
from api.live import fetch_live_status, fetch_recent_disruptions
from api.observability import configure_observability
from api.schemas import (
    ChatMessageResponse,
    ChatRequest,
    DisruptionResponse,
    LineStatusResponse,
    Mode,
    Problem,
)
from ingestion.tfl_client.client import TflClient


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

    # Open the TfL client only when an app key is wired. The station
    # resolver falls back gracefully to seed-only when the client is
    # ``None``, so an unset ``TFL_APP_KEY`` does not block the API.
    tfl_app_key = os.environ.get("TFL_APP_KEY")
    if tfl_app_key:
        tfl_client = TflClient(app_key=tfl_app_key)
        await tfl_client.__aenter__()
        app.state.tfl_client = tfl_client
    else:
        app.state.tfl_client = None
    # Lazy import: pulls langchain_anthropic + llama_index transitively.
    # Keeping it out of module scope shaves cold-start when DATABASE_URL
    # is unset (smoke tests, /health-only deploys).
    from api.agent.graph import compile_agent  # noqa: PLC0415

    app.state.agent = compile_agent(pool=pool, tfl_client=app.state.tfl_client)
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
        if app.state.tfl_client is not None:
            await app.state.tfl_client.__aexit__(None, None, None)
            app.state.tfl_client = None
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
app.state.tfl_client = None

configure_observability(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://tfl-monitor.vercel.app",
        "https://tfl-monitor.humbertolomeu.com",
    ],
    allow_origin_regex=r"^https://tfl-monitor-[a-z0-9-]+\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Accept", "Content-Type", "Authorization"],
)

# Optional debug router that proxies typed calls to the TfL Unified API so
# raw payload shapes can be inspected from Swagger. Kept out of
# ``contracts/openapi.yaml`` on purpose and gated on an env flag so it
# never reaches production.
if os.environ.get("TFL_DEBUG_PROXY") == "1":
    from api.debug_tfl import router as _debug_tfl_router  # noqa: PLC0415

    app.include_router(_debug_tfl_router)
    logfire.info("api_debug_tfl_router_enabled", service="tfl-monitor-api")


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
    tfl_client = getattr(request.app.state, "tfl_client", None)
    if tfl_client is None:
        return _problem(503, "Service Unavailable", "TfL client is not configured")
    try:
        return await fetch_live_status(tfl_client)
    except Exception:
        logfire.exception("get_status_live_failed")
        return _problem(502, "Bad Gateway", "Failed to fetch live status from TfL")


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
    tfl_client = getattr(request.app.state, "tfl_client", None)
    if tfl_client is None:
        return _problem(503, "Service Unavailable", "TfL client is not configured")
    if pool is None:
        return _problem(503, "Service Unavailable", "Database pool is not available")
    try:
        return await fetch_recent_disruptions(
            tfl_client,
            pool=pool,
            limit=limit,
            mode=mode,
        )
    except Exception:
        logfire.exception("get_recent_disruptions_failed")
        return _problem(502, "Bad Gateway", "Failed to fetch recent disruptions from TfL")


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
        completed = False
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
            completed = True
        except asyncio.CancelledError:
            raise
        except Exception:
            logfire.exception("chat_stream_failed", thread_id=body.thread_id)
            yield {"data": serialise(frame_end("error"))}
        finally:
            # Only persist the assistant turn when the stream finished
            # cleanly. Disconnects and errors leave ``completed=False`` so
            # ``analytics.chat_messages`` never sees a truncated reply.
            if completed and assistant_buffer:
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
