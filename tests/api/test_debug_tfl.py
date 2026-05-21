"""Unit tests for the debug TfL proxy router."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.debug_tfl import DEFAULT_MODES, router
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


def _json_handler(
    expected_path: str,
    body: Any,
    *,
    expected_params: dict[str, str] | None = None,
) -> httpx.MockTransport:
    """Return a MockTransport that asserts path/params then replies ``body`` as JSON."""

    def _handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == expected_path, (
            f"unexpected path: {request.url.path} (wanted {expected_path})"
        )
        assert request.url.params.get("app_key") == "test-key"
        for key, value in (expected_params or {}).items():
            assert request.url.params.get(key) == value, (
                f"expected {key}={value!r}, got {request.url.params.get(key)!r}"
            )
        return httpx.Response(200, content=json.dumps(body).encode("utf-8"))

    return httpx.MockTransport(_handle)


def test_main_gates_router_on_tfl_debug_proxy_env() -> None:
    """``api.main`` must only mount the debug router when ``TFL_DEBUG_PROXY=1``.

    Reads the source rather than reloading ``api.main`` so the assertion stays
    deterministic even when a developer runs ``TFL_DEBUG_PROXY=1 pytest`` — a
    module reload would replace ``api.main.app`` and break every other suite
    that already cached its reference at collection time.
    """
    main_source = Path(__file__).resolve().parents[2].joinpath("src/api/main.py").read_text()
    assert 'os.environ.get("TFL_DEBUG_PROXY") == "1"' in main_source
    assert "from api.debug_tfl import router" in main_source
    assert "app.include_router(_debug_tfl_router)" in main_source


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
    transport = _json_handler(
        f"/Line/Mode/{DEFAULT_MODES}/Status",
        payload,
        expected_params={"detail": "true"},
    )
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


def test_line_disruption_routes_to_disruption_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _json_handler(f"/Line/Mode/{DEFAULT_MODES}/Disruption", [])
    app = _build_app(monkeypatch, transport)

    response = TestClient(app).get("/api/v1/debug/tfl/line-disruption")

    assert response.status_code == 200
    assert response.json() == []


def test_yellow_banner_routes_to_status_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    body = [{"text": "Planned closure on Saturday", "timeFrom": "2026-05-24T00:00:00Z"}]
    transport = _json_handler("/status/yellowbannermessages", body)
    app = _build_app(monkeypatch, transport)

    response = TestClient(app).get("/api/v1/debug/tfl/yellow-banner")

    assert response.status_code == 200
    assert response.json() == body


def test_red_banner_routes_to_status_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    body = [{"text": "Severe disruption network-wide", "timeFrom": "2026-05-20T00:00:00Z"}]
    transport = _json_handler("/status/redbannermessages", body)
    app = _build_app(monkeypatch, transport)

    response = TestClient(app).get("/api/v1/debug/tfl/red-banner")

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


def test_missing_app_key_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing TFL_APP_KEY is a local misconfig — must surface as 503, not 502."""
    monkeypatch.delenv("TFL_APP_KEY", raising=False)
    # No transport patching: real ``TflClient.from_env`` runs and raises
    # before any HTTP call.
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/api/v1/debug/tfl/status")

    assert response.status_code == 503
    assert "TFL_APP_KEY" in response.json()["detail"]


def test_invalid_modes_rejected_with_422(monkeypatch: pytest.MonkeyPatch) -> None:
    """Path-shaping attempts via ``modes`` must be rejected at the handler boundary."""
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, content=b"[]"))
    app = _build_app(monkeypatch, transport)

    response = TestClient(app).get("/api/v1/debug/tfl/status", params={"modes": "../etc"})

    assert response.status_code == 422


def test_invalid_stop_id_rejected_with_422(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, content=b"[]"))
    app = _build_app(monkeypatch, transport)

    response = TestClient(app).get("/api/v1/debug/tfl/arrivals/has-dash")

    assert response.status_code == 422
