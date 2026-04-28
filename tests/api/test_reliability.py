"""Unit tests for the ``/api/v1/reliability/{line_id}`` endpoint."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from api.db import RELIABILITY_AGG_SQL, RELIABILITY_HISTOGRAM_SQL
from api.main import app


def _agg(line_id: str = "victoria", sample_size: int = 2016, pct: float = 94.2) -> dict[str, Any]:
    return {
        "line_id": line_id,
        "line_name": line_id.title(),
        "mode": "tube",
        "sample_size": sample_size,
        "reliability_percent": pct,
    }


def test_happy_path(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory(
        [_agg()],
        [
            {"severity": "6", "count": 12},
            {"severity": "9", "count": 48},
            {"severity": "10", "count": 1956},
        ],
    )
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/reliability/victoria", params={"window": 14})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "line_id": "victoria",
        "line_name": "Victoria",
        "mode": "tube",
        "window_days": 14,
        "reliability_percent": 94.2,
        "sample_size": 2016,
        "severity_histogram": {"6": 12, "9": 48, "10": 1956},
    }
    agg_sql, agg_params = pool.conn.executed[0]
    hist_sql, hist_params = pool.conn.executed[1]
    assert agg_sql == RELIABILITY_AGG_SQL
    assert hist_sql == RELIABILITY_HISTOGRAM_SQL
    assert agg_params == {"line_id": "victoria", "window": 14}
    assert hist_params == {"line_id": "victoria", "window": 14}


def test_default_window_is_seven(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory([_agg()], [{"severity": "10", "count": 2016}])
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/reliability/victoria")
    assert response.status_code == 200
    assert response.json()["window_days"] == 7


def test_histogram_excludes_zero_counts(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory(
        [_agg(sample_size=10)],
        [
            {"severity": "10", "count": 10},
            {"severity": "6", "count": 0},
        ],
    )
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/reliability/victoria")
    assert response.status_code == 200
    assert response.json()["severity_histogram"] == {"10": 10}


def test_empty_result_returns_404(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory([])
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/reliability/ghost")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert "ghost" in response.json()["detail"]


def test_zero_sample_size_returns_404(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory([_agg(sample_size=0, pct=0.0)])
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/reliability/victoria")
    assert response.status_code == 404


def test_null_sample_size_returns_404(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    """``SUM`` returns ``NULL`` when no rows match; treat as no data."""
    row = _agg(sample_size=0, pct=0.0)
    row["sample_size"] = None
    pool = fake_pool_factory([row])
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/reliability/victoria")
    assert response.status_code == 404


def test_window_out_of_range_returns_422(attach_pool: Callable[[Any], None]) -> None:
    response_low = TestClient(app).get("/api/v1/reliability/victoria", params={"window": 0})
    response_high = TestClient(app).get("/api/v1/reliability/victoria", params={"window": 91})
    assert response_low.status_code == 422
    assert response_high.status_code == 422


def test_missing_pool_returns_503(attach_pool: Callable[[Any], None]) -> None:
    attach_pool(None)
    response = TestClient(app).get("/api/v1/reliability/victoria")
    assert response.status_code == 503
