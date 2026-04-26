"""FastAPI entrypoint for the tfl-monitor API.

Endpoint bodies are intentionally stubs that return HTTP 501 until the owning
work package lands (TM-D2 onwards). The shape of the API is fixed by
``contracts/openapi.yaml``.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.observability import configure_observability

app = FastAPI(
    title="tfl-monitor API",
    version="0.0.1",
    description="See contracts/openapi.yaml for the full spec.",
)

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


@app.get("/health", operation_id="get_health")
async def get_health() -> dict[str, Any]:
    """Liveness probe used by container orchestrators and uptime checks."""
    return {"status": "ok", "dependencies": {}}


@app.get("/api/v1/status/live", operation_id="get_status_live", response_model=None)
async def get_status_live() -> NoReturn:
    _not_implemented("Not implemented — see TM-D2")


@app.get("/api/v1/status/history", operation_id="get_status_history", response_model=None)
async def get_status_history() -> NoReturn:
    _not_implemented("Not implemented — see TM-D2")


@app.get(
    "/api/v1/reliability/{line_id}",
    operation_id="get_line_reliability",
    response_model=None,
)
async def get_line_reliability(line_id: str) -> NoReturn:
    _not_implemented("Not implemented — see TM-D2")


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
