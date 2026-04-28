"""Integration test for ``/api/v1/status/live`` against a real Postgres.

Gated on the ``integration`` pytest marker so the default
``uv run task test`` run stays hermetic. Run explicitly with::

    DATABASE_URL=postgresql://tflmonitor:change_me@localhost:5432/tflmonitor \\
        uv run pytest -m integration tests/integration/test_status_live.py -v
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

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


def _payload(line_id: str, severity: int = 10) -> dict[str, Any]:
    return {
        "line_id": line_id,
        "line_name": line_id.title(),
        "mode": "tube",
        "status_severity": severity,
        "status_severity_description": "Good Service" if severity == 10 else "Severe Delays",
        "reason": None if severity == 10 else "Test reason",
        "valid_from": "2026-04-28T06:00:00+00:00",
        "valid_to": "2026-04-28T23:59:00+00:00",
    }


@pytest.fixture
def cleanup_raw_line_status() -> Iterator[None]:
    """Strip the rows this test inserts so consecutive runs stay isolated."""
    marker = "tfl-monitor.integration.status-live"
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM raw.line_status WHERE source = %s", (marker,))
        conn.commit()
    yield
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM raw.line_status WHERE source = %s", (marker,))
        conn.commit()


def test_live_returns_only_recent_rows(cleanup_raw_line_status: None) -> None:
    marker = "tfl-monitor.integration.status-live"
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO raw.line_status (event_type, source, payload, ingested_at) "
                "VALUES (%s, %s, %s::jsonb, now() - interval '60 minutes')",
                ("line-status.snapshot", marker, json.dumps(_payload("piccadilly", 6))),
            )
            cur.execute(
                "INSERT INTO raw.line_status (event_type, source, payload, ingested_at) "
                "VALUES (%s, %s, %s::jsonb, now())",
                ("line-status.snapshot", marker, json.dumps(_payload("victoria", 10))),
            )
        conn.commit()

    with TestClient(app=__import__("api.main", fromlist=["app"]).app) as client:
        response = client.get("/api/v1/status/live")

    assert response.status_code == 200
    body = response.json()
    line_ids = {item["line_id"] for item in body}
    assert "victoria" in line_ids
    assert "piccadilly" not in line_ids
