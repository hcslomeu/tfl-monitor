"""Unit tests for the ``/api/v1/bus/{stop_id}/punctuality`` endpoint."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from api.db import BUS_PUNCTUALITY_SQL, BUS_STOP_NAME_SQL
from api.main import app


def _agg(
    *,
    sample_size: int = 100,
    late_count: int = 10,
    on_time_count: int = 80,
    early_count: int = 10,
) -> dict[str, Any]:
    return {
        "sample_size": sample_size,
        "late_count": late_count,
        "on_time_count": on_time_count,
        "early_count": early_count,
    }


def _name_row(station_name: str = "Trafalgar Square") -> dict[str, Any]:
    return {"station_name": station_name}


def test_happy_path_buckets(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory(
        [_agg(sample_size=100, late_count=10, on_time_count=80, early_count=10)],
        [_name_row("Trafalgar Square")],
    )
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/bus/490008660N/punctuality")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "stop_id": "490008660N",
        "stop_name": "Trafalgar Square",
        "window_days": 7,
        "on_time_percent": 80.0,
        "early_percent": 10.0,
        "late_percent": 10.0,
        "sample_size": 100,
    }
    agg_sql, agg_params = pool.conn.executed[0]
    name_sql, name_params = pool.conn.executed[1]
    assert agg_sql == BUS_PUNCTUALITY_SQL
    assert name_sql == BUS_STOP_NAME_SQL
    assert agg_params == {"stop_id": "490008660N", "window": 7}
    assert name_params == {"stop_id": "490008660N"}


def test_percent_rounds_to_one_decimal(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory(
        [_agg(sample_size=3, late_count=1, on_time_count=1, early_count=1)],
        [_name_row()],
    )
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/bus/stop-1/punctuality")
    assert response.status_code == 200
    body = response.json()
    # 1/3 -> 33.333... rounded to 33.3
    assert body["on_time_percent"] == 33.3
    assert body["early_percent"] == 33.3
    assert body["late_percent"] == 33.3


def test_zero_sample_returns_404(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory(
        [_agg(sample_size=0, late_count=0, on_time_count=0, early_count=0)],
    )
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/bus/490008660N/punctuality")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert "490008660N" in response.json()["detail"]


def test_aggregate_returns_no_row_returns_404(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory([])
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/bus/490008660N/punctuality")

    assert response.status_code == 404


def test_missing_station_name_returns_404(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory(
        [_agg()],
        [],
    )
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/bus/490008660N/punctuality")

    assert response.status_code == 404


def test_missing_pool_returns_503(attach_pool: Callable[[Any], None]) -> None:
    attach_pool(None)

    response = TestClient(app).get("/api/v1/bus/490008660N/punctuality")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 503
    assert body["title"] == "Service Unavailable"
