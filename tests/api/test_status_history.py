"""Unit tests for the ``/api/v1/status/history`` endpoint."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from api.db import HISTORY_SQL
from api.main import app


def _row(line_id: str, valid_from: datetime) -> dict[str, Any]:
    return {
        "line_id": line_id,
        "line_name": line_id.title(),
        "mode": "tube",
        "status_severity": 10,
        "status_severity_description": "Good Service",
        "reason": None,
        "valid_from": valid_from,
        "valid_to": valid_from.replace(hour=23, minute=59),
    }


def test_happy_path(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory(
        [
            _row("victoria", datetime(2026, 4, 20, 6, 0, tzinfo=UTC)),
            _row("victoria", datetime(2026, 4, 21, 6, 0, tzinfo=UTC)),
        ]
    )
    attach_pool(pool)

    response = TestClient(app).get(
        "/api/v1/status/history",
        params={
            "from": "2026-04-20T00:00:00Z",
            "to": "2026-04-22T00:00:00Z",
            "line_id": "victoria",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert all(item["line_id"] == "victoria" for item in body)
    sql, params = pool.conn.executed[0]
    assert sql == HISTORY_SQL
    assert params is not None
    assert params["line_id"] == "victoria"
    assert params["from"].tzinfo is not None
    assert params["to"] > params["from"]


def test_from_after_to_returns_400(attach_pool: Callable[[Any], None]) -> None:
    response = TestClient(app).get(
        "/api/v1/status/history",
        params={"from": "2026-04-22T00:00:00Z", "to": "2026-04-20T00:00:00Z"},
    )
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    assert "before" in response.json()["detail"]


def test_window_over_thirty_days_returns_400(attach_pool: Callable[[Any], None]) -> None:
    response = TestClient(app).get(
        "/api/v1/status/history",
        params={"from": "2026-03-01T00:00:00Z", "to": "2026-04-15T00:00:00Z"},
    )
    assert response.status_code == 400
    assert "30-day" in response.json()["detail"]


def test_line_id_filter_passes_through(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory([])
    attach_pool(pool)

    TestClient(app).get(
        "/api/v1/status/history",
        params={
            "from": "2026-04-20T00:00:00Z",
            "to": "2026-04-21T00:00:00Z",
            "line_id": "piccadilly",
        },
    )

    _sql, params = pool.conn.executed[0]
    assert params is not None
    assert params["line_id"] == "piccadilly"


def test_missing_line_id_filter_passes_none(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory([])
    attach_pool(pool)

    TestClient(app).get(
        "/api/v1/status/history",
        params={"from": "2026-04-20T00:00:00Z", "to": "2026-04-21T00:00:00Z"},
    )

    _sql, params = pool.conn.executed[0]
    assert params is not None
    assert params["line_id"] is None


def test_missing_pool_returns_503(attach_pool: Callable[[Any], None]) -> None:
    attach_pool(None)
    response = TestClient(app).get(
        "/api/v1/status/history",
        params={"from": "2026-04-20T00:00:00Z", "to": "2026-04-21T00:00:00Z"},
    )
    assert response.status_code == 503
