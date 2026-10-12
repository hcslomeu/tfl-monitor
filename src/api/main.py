"""FastAPI entrypoint for the tfl-monitor API.

Status and disruption endpoints read the TfL Unified API live through a
shared ``TflClient`` opened by the lifespan. The chat agent is compiled
once in the lifespan and cached on ``app.state.agent``. The API is
stateless (ADR 015): no database. The shape of the API is fixed by
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

from api.agent.streaming import frame_end, project, serialise
from api.live import fetch_live_status, fetch_recent_disruptions
from api.observability import configure_observability
from api.schemas import (
    ChatRequest,
    DisruptionResponse,
    LineStatusResponse,
    Mode,
    Problem,
)
from ingestion.tfl_client.client import TflClient

# Cached GET responses are shared by every dashboard viewer: the CDN
# collapses concurrent polls into at most one function run per window.
_LIVE_CACHE_CONTROL = "public, s-maxage=30, stale-while-revalidate=30"

# LangGraph super-step ceiling per chat turn (roughly five tool calls).
_CHAT_RECURSION_LIMIT = 12

_CHAT_UNAVAILABLE_MESSAGE = (
    "The assistant is unavailable right now (the demo's monthly AI budget "
    "may be used up). Live line status on the dashboard still works."
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open and close the shared TfL client and compile the chat agent.

    When ``TFL_APP_KEY`` is unset the TfL client stays ``None`` and the
    live endpoints return ``503``; ``/health`` keeps working without
    secrets. When ``ANTHROPIC_API_KEY`` is unset the agent stays ``None``
    and ``/chat/stream`` returns ``503``.
    """
    tfl_app_key = os.environ.get("TFL_APP_KEY")
    tfl_client: TflClient | None = None
    if tfl_app_key:
        tfl_client = TflClient(app_key=tfl_app_key)
        await tfl_client.__aenter__()
    app.state.tfl_client = tfl_client

    # Lazy import: pulls langchain_anthropic + langgraph transitively.
    from api.agent.graph import compile_agent  # noqa: PLC0415

    app.state.agent = compile_agent(tfl_client=tfl_client)
    logfire.info(
        "api_started",
        service="tfl-monitor-api",
        tfl_client_configured=tfl_client is not None,
        chat_agent_configured=app.state.agent is not None,
    )
    try:
        yield
    finally:
        if tfl_client is not None:
            await tfl_client.__aexit__(None, None, None)
        app.state.tfl_client = None
        app.state.agent = None


app = FastAPI(
    title="tfl-monitor API",
    version="0.0.1",
    description="See contracts/openapi.yaml for the full spec.",
    lifespan=lifespan,
)

# Pre-seed so unit tests that build ``TestClient(app)`` outside an
# ``async with`` block (and therefore skip the lifespan) still see the
# attribute. Tests that need a client / agent monkeypatch these slots.
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
async def get_status_live(
    request: Request, response: Response
) -> list[LineStatusResponse] | Response:
    tfl_client = getattr(request.app.state, "tfl_client", None)
    if tfl_client is None:
        return _problem(503, "Service Unavailable", "TfL client is not configured")
    try:
        rows = await fetch_live_status(tfl_client)
    except Exception:
        logfire.exception("get_status_live_failed")
        return _problem(502, "Bad Gateway", "Failed to fetch live status from TfL")
    response.headers["Cache-Control"] = _LIVE_CACHE_CONTROL
    return rows


@app.get(
    "/api/v1/disruptions/recent",
    operation_id="get_recent_disruptions",
    response_model=list[DisruptionResponse],
)
async def get_recent_disruptions(
    request: Request,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    mode: Annotated[Mode | None, Query()] = None,
) -> list[DisruptionResponse] | Response:
    tfl_client = getattr(request.app.state, "tfl_client", None)
    if tfl_client is None:
        return _problem(503, "Service Unavailable", "TfL client is not configured")
    try:
        rows = await fetch_recent_disruptions(tfl_client, limit=limit, mode=mode)
    except Exception:
        logfire.exception("get_recent_disruptions_failed")
        return _problem(502, "Bad Gateway", "Failed to fetch recent disruptions from TfL")
    response.headers["Cache-Control"] = _LIVE_CACHE_CONTROL
    return rows


@app.post("/api/v1/chat/stream", operation_id="post_chat_stream", response_model=None)
async def post_chat_stream(request: Request, body: ChatRequest) -> Response:
    """Stream a LangGraph agent response over Server-Sent Events.

    Conversation memory lives in the agent's in-process checkpointer,
    keyed by ``thread_id``; nothing is persisted (ADR 015).
    """
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        return _problem(503, "Service Unavailable", "Chat agent is not configured")

    async def event_stream() -> AsyncIterator[dict[str, str]]:
        from anthropic import APIStatusError  # noqa: PLC0415

        config: dict[str, Any] = {
            "configurable": {"thread_id": body.thread_id},
            "recursion_limit": _CHAT_RECURSION_LIMIT,
        }
        inputs = {"messages": [{"role": "user", "content": body.message}]}
        try:
            async for mode, payload in agent.astream(
                inputs, config=config, stream_mode=["messages", "updates"]
            ):
                if await request.is_disconnected():
                    return
                for frame in project(mode, payload):
                    yield {"data": serialise(frame)}
            yield {"data": serialise(frame_end())}
        except asyncio.CancelledError:
            raise
        except APIStatusError as exc:
            # Spend-limit, auth, and rate-limit rejections from Anthropic:
            # tell the user plainly instead of a bare error bubble.
            logfire.warn(
                "chat_llm_rejected",
                thread_id=body.thread_id,
                status_code=exc.status_code,
            )
            yield {"data": serialise({"type": "token", "content": _CHAT_UNAVAILABLE_MESSAGE})}
            yield {"data": serialise(frame_end("error"))}
        except Exception:
            logfire.exception("chat_stream_failed", thread_id=body.thread_id)
            yield {"data": serialise(frame_end("error"))}

    return EventSourceResponse(event_stream(), ping=15)
