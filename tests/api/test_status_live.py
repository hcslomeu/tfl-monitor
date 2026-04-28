"""Unit tests for the ``/api/v1/status/live`` endpoint."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from api.db import LIVE_STATUS_SQL
from api.main import app


def _row(line_id: str, severity: int = 10) -> dict[str, Any]:
    return {
        "line_id": line_id,
        "line_name": line_id.title(),
        "mode": "tube",
        "status_severity": severity,
        "status_severity_description": "Good Service",
        "reason": None,
        "valid_from": datetime(2026, 4, 28, 6, 0, tzinfo=UTC),
        "valid_to": datetime(2026, 4, 28, 23, 59, tzinfo=UTC),
    }


def test_returns_rows_in_line_id_order(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory([_row("piccadilly", 6), _row("victoria")])
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/status/live")

    assert response.status_code == 200
    body = response.json()
    assert [item["line_id"] for item in body] == ["piccadilly", "victoria"]
    assert body[0]["status_severity"] == 6
    assert body[1]["valid_from"].endswith("Z") or body[1]["valid_from"].endswith("+00:00")
    assert pool.conn.executed[0][0] == LIVE_STATUS_SQL


def test_empty_result_returns_empty_list(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory([])
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/status/live")

    assert response.status_code == 200
    assert response.json() == []


def test_missing_pool_returns_503(attach_pool: Callable[[Any], None]) -> None:
    attach_pool(None)

    response = TestClient(app).get("/api/v1/status/live")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 503
    assert body["title"] == "Service Unavailable"
    assert "Database pool" in body["detail"]
