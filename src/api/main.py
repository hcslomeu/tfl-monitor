"""FastAPI entrypoint for the tfl-monitor API.

Status and reliability endpoints (TM-D2) query Postgres via a shared
``AsyncConnectionPool`` opened by the lifespan. Disruptions, bus, and
chat endpoints stay stubbed at HTTP 501 until their owning WPs (TM-D3
and TM-D5) land. The shape of the API is fixed by
``contracts/openapi.yaml``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Annotated, Any, NoReturn

import logfire
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from api.db import build_pool, fetch_live_status, fetch_reliability, fetch_status_history
from api.observability import configure_observability
from api.schemas import LineReliabilityResponse, LineStatusResponse, Problem

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
    logfire.info(
        "api_db_pool_opened",
        service="tfl-monitor-api",
        database_url_configured=True,
        pool_min_size=1,
        pool_max_size=4,
    )
    try:
        yield
    finally:
        await pool.close()
        app.state.db_pool = None
        logfire.info("api_db_pool_closed", service="tfl-monitor-api")


app = FastAPI(
    title="tfl-monitor API",
    version="0.0.1",
    description="See contracts/openapi.yaml for the full spec.",
    lifespan=lifespan,
)

# Pre-seed so unit tests that build ``TestClient(app)`` outside an
# ``async with`` block (and therefore skip the lifespan) still see the
# attribute. Tests that need a live pool monkeypatch this slot.
app.state.db_pool = None

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


def _not_implemented(detail: str) -> NoReturn:
    raise HTTPException(status_code=501, detail=detail)


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
    response_model=None,
)
async def get_recent_disruptions() -> NoReturn:
    _not_implemented("Not implemented — see TM-D3")


@app.get(
    "/api/v1/bus/{stop_id}/punctuality",
    operation_id="get_bus_punctuality",
    response_model=None,
)
async def get_bus_punctuality(stop_id: str) -> NoReturn:
    _not_implemented("Not implemented — see TM-D3")


@app.post("/api/v1/chat/stream", operation_id="post_chat_stream", response_model=None)
async def post_chat_stream() -> NoReturn:
    _not_implemented("Not implemented — see TM-D5")


@app.get(
    "/api/v1/chat/{thread_id}/history",
    operation_id="get_chat_history",
    response_model=None,
)
async def get_chat_history(thread_id: str) -> NoReturn:
    _not_implemented("Not implemented — see TM-D5")
