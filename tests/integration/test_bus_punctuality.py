"""Integration test for ``/api/v1/bus/{stop_id}/punctuality`` against a real Postgres.

Seeds ``analytics.stg_arrivals`` directly so the test does not need a
prior dbt run; the dbt -> staging contract is covered by the dbt
tests in ``TM-C3``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

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


MARKER = "tfl-monitor.integration.bus-punctuality"
TEST_STOP_ID = "490008660N-int"


def _ensure_table(cur: object) -> None:
    """Create the staging schema/table if dbt has not materialised it yet."""
    assert hasattr(cur, "execute")
    cur.execute("CREATE SCHEMA IF NOT EXISTS analytics")  # type: ignore[attr-defined]
    cur.execute(  # type: ignore[attr-defined]
        """
        CREATE TABLE IF NOT EXISTS analytics.stg_arrivals (
            event_id UUID,
            ingested_at TIMESTAMPTZ,
            event_type TEXT,
            source TEXT,
            arrival_id TEXT,
            station_id TEXT,
            station_name TEXT,
            line_id TEXT,
            platform_name TEXT,
            direction TEXT,
            destination TEXT,
            expected_arrival TIMESTAMPTZ,
            time_to_station_seconds INT,
            vehicle_id TEXT
        )
        """
    )


@pytest.fixture
def cleanup_stg_arrivals() -> Iterator[None]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            _ensure_table(cur)
            cur.execute("DELETE FROM analytics.stg_arrivals WHERE source = %s", (MARKER,))
        conn.commit()
    yield
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM analytics.stg_arrivals WHERE source = %s", (MARKER,))
        conn.commit()


def test_punctuality_buckets_compute_from_time_to_station(
    cleanup_stg_arrivals: None,
) -> None:
    from api.main import app

    # Distribute predictions across all three buckets:
    #   on_time  : tts in [0, 300]      -> 2 rows
    #   early    : tts > 300            -> 1 row
    #   late     : tts < 0              -> 1 row
    rows = [
        (60, "Trafalgar Square"),
        (120, "Trafalgar Square"),
        (600, "Trafalgar Square"),
        (-30, "Trafalgar Square"),
    ]
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for time_to_station, station_name in rows:
                cur.execute(
                    """
                    INSERT INTO analytics.stg_arrivals (
                        event_id, ingested_at, event_type, source,
                        arrival_id, station_id, station_name, line_id,
                        platform_name, direction, destination,
                        expected_arrival, time_to_station_seconds, vehicle_id
                    ) VALUES (
                        gen_random_uuid(), now(), %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        now() + (%s * interval '1 second'), %s, NULL
                    )
                    """,
                    (
                        "arrivals.snapshot",
                        MARKER,
                        f"arr-{uuid4().hex}",
                        TEST_STOP_ID,
                        station_name,
                        "24",
                        "Stop B",
                        "outbound",
                        "Pimlico",
                        time_to_station,
                        time_to_station,
                    ),
                )
        conn.commit()

    with TestClient(app) as client:
        response = client.get(f"/api/v1/bus/{TEST_STOP_ID}/punctuality")

    assert response.status_code == 200
    body = response.json()
    assert body["stop_id"] == TEST_STOP_ID
    assert body["stop_name"] == "Trafalgar Square"
    assert body["window_days"] == 7
    assert body["sample_size"] == 4
    assert body["on_time_percent"] == 50.0
    assert body["early_percent"] == 25.0
    assert body["late_percent"] == 25.0


def test_unknown_stop_returns_404(cleanup_stg_arrivals: None) -> None:
    from api.main import app

    missing_stop = f"no-such-stop-{uuid4().hex}"
    with TestClient(app) as client:
        response = client.get(f"/api/v1/bus/{missing_stop}/punctuality")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert missing_stop in response.json()["detail"]
