"""Unit tests for the debug TfL proxy router."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from api.debug_tfl import DEFAULT_MODES, router
from api.main import app as production_app
from ingestion.tfl_client import TflClient


def _build_app(monkeypatch: pytest.MonkeyPatch, handler: httpx.MockTransport) -> FastAPI:
    """Return a fresh FastAPI app wired to the debug router with a mocked TfL transport."""
    monkeypatch.setenv("TFL_APP_KEY", "test-key")

    def patched_from_env(cls: type[TflClient], **kwargs: Any) -> TflClient:
        return cls(app_key="test-key", transport=handler, **kwargs)

    monkeypatch.setattr(TflClient, "from_env", classmethod(patched_from_env))

    app = FastAPI()
    app.include_router(router)
    return app


def _json_handler(expected_path: str, body: Any) -> httpx.MockTransport:
    """Return a MockTransport that asserts the path then replies ``body`` as JSON."""

    def _handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == expected_path, (
            f"unexpected path: {request.url.path} (wanted {expected_path})"
        )
        assert request.url.params.get("app_key") == "test-key"
        return httpx.Response(200, content=json.dumps(body).encode("utf-8"))

    return httpx.MockTransport(_handle)


def test_router_not_mounted_by_default() -> None:
    """Without ``TFL_DEBUG_PROXY=1`` the proxy routes must be absent from the prod app."""
    paths = {route.path for route in production_app.routes if isinstance(route, APIRoute)}
    debug_paths = {p for p in paths if p.startswith("/api/v1/debug/tfl")}
    assert debug_paths == set(), f"debug routes leaked into prod app: {debug_paths}"


def test_status_detail_forwards_query_and_returns_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = [
        {
            "id": "district",
            "name": "District",
            "lineStatuses": [
                {
                    "statusSeverity": 9,
                    "statusSeverityDescription": "Minor Delays",
                    "reason": "District Line: Minor delays between Turnham Green and Richmond",
                    "disruption": {"description": "Signal failure"},
                }
            ],
        }
    ]
    transport = _json_handler(f"/Line/Mode/{DEFAULT_MODES}/Status", payload)
    app = _build_app(monkeypatch, transport)

    response = TestClient(app).get("/api/v1/debug/tfl/status-detail")

    assert response.status_code == 200
    assert response.json() == payload


def test_status_passes_through_custom_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _json_handler("/Line/Mode/tube/Status", [])
    app = _build_app(monkeypatch, transport)

    response = TestClient(app).get("/api/v1/debug/tfl/status", params={"modes": "tube"})

    assert response.status_code == 200
    assert response.json() == []


def test_yellow_banner_routes_to_status_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    body = [{"text": "Planned closure on Saturday", "timeFrom": "2026-05-24T00:00:00Z"}]
    transport = _json_handler("/status/yellowbannermessages", body)
    app = _build_app(monkeypatch, transport)

    response = TestClient(app).get("/api/v1/debug/tfl/yellow-banner")

    assert response.status_code == 200
    assert response.json() == body


def test_lift_disruptions_routes_to_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _json_handler("/Disruptions/Lifts/v2", [])
    app = _build_app(monkeypatch, transport)

    response = TestClient(app).get("/api/v1/debug/tfl/lift-disruptions")

    assert response.status_code == 200


def test_arrivals_path_includes_stop_id(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _json_handler("/StopPoint/940GZZLUOXC/Arrivals", [])
    app = _build_app(monkeypatch, transport)

    response = TestClient(app).get("/api/v1/debug/tfl/arrivals/940GZZLUOXC")

    assert response.status_code == 200


def test_upstream_error_returns_502(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    app = _build_app(monkeypatch, httpx.MockTransport(_fail))

    response = TestClient(app).get("/api/v1/debug/tfl/status")

    assert response.status_code == 502
    assert "HTTP 500" in response.json()["detail"]
