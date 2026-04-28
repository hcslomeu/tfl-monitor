"""Integration test for ``/api/v1/status/history`` against a real Postgres.

Seeds ``analytics.stg_line_status`` directly so the test does not need a
prior dbt run; the dbt → staging contract is covered by the dbt tests in
``TM-C2``.
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


MARKER = "tfl-monitor.integration.status-history"


def _ensure_table(cur: object) -> None:
    """Create the staging schema/table if dbt has not materialised it yet."""
    assert hasattr(cur, "execute")
    cur.execute("CREATE SCHEMA IF NOT EXISTS analytics")  # type: ignore[attr-defined]
    cur.execute(  # type: ignore[attr-defined]
        """
        CREATE TABLE IF NOT EXISTS analytics.stg_line_status (
            event_id UUID,
            ingested_at TIMESTAMPTZ,
            event_type TEXT,
            source TEXT,
            line_id TEXT,
            line_name TEXT,
            mode TEXT,
            status_severity INT,
            status_severity_description TEXT,
            reason TEXT,
            valid_from TIMESTAMPTZ,
            valid_to TIMESTAMPTZ
        )
        """
    )


@pytest.fixture
def cleanup_stg_line_status() -> Iterator[None]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            _ensure_table(cur)
            cur.execute("DELETE FROM analytics.stg_line_status WHERE source = %s", (MARKER,))
        conn.commit()
    yield
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM analytics.stg_line_status WHERE source = %s", (MARKER,))
        conn.commit()


def test_history_returns_filtered_rows(cleanup_stg_line_status: None) -> None:
    from api.main import app

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for line_id, valid_from in (
                ("victoria", "2026-04-20T06:00:00+00:00"),
                ("victoria", "2026-04-21T06:00:00+00:00"),
                ("piccadilly", "2026-04-20T06:00:00+00:00"),
            ):
                cur.execute(
                    """
                    INSERT INTO analytics.stg_line_status (
                        event_id, ingested_at, event_type, source,
                        line_id, line_name, mode,
                        status_severity, status_severity_description,
                        reason, valid_from, valid_to
                    ) VALUES (
                        gen_random_uuid(), now(), %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s
                    )
                    """,
                    (
                        "line-status.snapshot",
                        MARKER,
                        line_id,
                        line_id.title(),
                        "tube",
                        10,
                        "Good Service",
                        None,
                        valid_from,
                        "2026-04-30T23:59:00+00:00",
                    ),
                )
        conn.commit()

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/status/history",
            params={
                "from": "2026-04-19T00:00:00Z",
                "to": "2026-04-22T00:00:00Z",
                "line_id": "victoria",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert {item["line_id"] for item in body} == {"victoria"}
    assert len(body) == 2
    assert body[0]["valid_from"] <= body[1]["valid_from"]
