"""Integration test for ``/api/v1/reliability/{line_id}`` against a real Postgres.

Seeds ``analytics.mart_tube_reliability_daily`` directly so the test does
not need a prior dbt run; the dbt → mart contract is covered by the dbt
tests in ``TM-C2``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

psycopg = pytest.importorskip("psycopg")

DATABASE_URL = os.environ.get("DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="DATABASE_URL not set; skipping Postgres-dependent integration tests",
    ),
]


def _ensure_table(cur: object) -> None:
    assert hasattr(cur, "execute")
    cur.execute("CREATE SCHEMA IF NOT EXISTS analytics")  # type: ignore[attr-defined]
    cur.execute(  # type: ignore[attr-defined]
        """
        CREATE TABLE IF NOT EXISTS analytics.mart_tube_reliability_daily (
            line_id TEXT,
            line_name TEXT,
            mode TEXT,
            calendar_date DATE,
            status_severity INT,
            status_severity_description TEXT,
            snapshot_count INT,
            first_observed_at TIMESTAMPTZ,
            last_observed_at TIMESTAMPTZ,
            minutes_observed_estimate NUMERIC(12, 2)
        )
        """
    )


@pytest.fixture
def cleanup_mart() -> Iterator[None]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            _ensure_table(cur)
            cur.execute(
                "DELETE FROM analytics.mart_tube_reliability_daily WHERE line_id = %s",
                ("victoria-int",),
            )
        conn.commit()
    yield
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM analytics.mart_tube_reliability_daily WHERE line_id = %s",
                ("victoria-int",),
            )
        conn.commit()


def test_reliability_aggregate_and_histogram(cleanup_mart: None) -> None:
    from api.main import app

    rows = [
        ("victoria-int", "Victoria", "tube", 0, 10, "Good Service", 1956),
        ("victoria-int", "Victoria", "tube", 0, 9, "Minor Delays", 48),
        ("victoria-int", "Victoria", "tube", 0, 6, "Severe Delays", 12),
    ]
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for line_id, line_name, mode, day_offset, severity, severity_desc, count in rows:
                cur.execute(
                    """
                    INSERT INTO analytics.mart_tube_reliability_daily (
                        line_id, line_name, mode, calendar_date,
                        status_severity, status_severity_description, snapshot_count,
                        first_observed_at, last_observed_at, minutes_observed_estimate
                    ) VALUES (%s, %s, %s, current_date - %s, %s, %s, %s,
                             now(), now(), 0)
                    """,
                    (line_id, line_name, mode, day_offset, severity, severity_desc, count),
                )
        conn.commit()

    with TestClient(app) as client:
        response = client.get("/api/v1/reliability/victoria-int", params={"window": 7})

    assert response.status_code == 200
    body = response.json()
    assert body["line_id"] == "victoria-int"
    assert body["sample_size"] == 2016
    assert body["reliability_percent"] == pytest.approx(97.0, abs=0.1)
    assert body["severity_histogram"] == {"6": 12, "9": 48, "10": 1956}


def test_unknown_line_returns_404(cleanup_mart: None) -> None:
    from api.main import app

    with TestClient(app) as client:
        response = client.get("/api/v1/reliability/no-such-line")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
