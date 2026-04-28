"""Integration test for ``/api/v1/disruptions/recent`` against a real Postgres.

Seeds ``analytics.stg_disruptions`` directly so the test does not need
a prior dbt run; the dbt -> staging contract is covered by the dbt
tests in ``TM-C3``.
"""

from __future__ import annotations

import json
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


MARKER = "tfl-monitor.integration.disruptions-recent"


def _ensure_table(cur: object) -> None:
    """Create the staging schema/table if dbt has not materialised it yet."""
    assert hasattr(cur, "execute")
    cur.execute("CREATE SCHEMA IF NOT EXISTS analytics")  # type: ignore[attr-defined]
    cur.execute(  # type: ignore[attr-defined]
        """
        CREATE TABLE IF NOT EXISTS analytics.stg_disruptions (
            event_id UUID,
            ingested_at TIMESTAMPTZ,
            event_type TEXT,
            source TEXT,
            disruption_id TEXT,
            category TEXT,
            category_description TEXT,
            description TEXT,
            summary TEXT,
            closure_text TEXT,
            severity INT,
            created TIMESTAMPTZ,
            last_update TIMESTAMPTZ,
            affected_routes JSONB,
            affected_stops JSONB
        )
        """
    )


@pytest.fixture
def cleanup_stg_disruptions() -> Iterator[None]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            _ensure_table(cur)
            cur.execute("DELETE FROM analytics.stg_disruptions WHERE source = %s", (MARKER,))
        conn.commit()
    yield
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM analytics.stg_disruptions WHERE source = %s", (MARKER,))
        conn.commit()


def test_recent_disruptions_returns_rows_in_recency_order(
    cleanup_stg_disruptions: None,
) -> None:
    from api.main import app

    rows = [
        (
            "2026-04-22-PIC-001",
            "2026-04-22T08:05:00+00:00",  # last_update -- newest
            "Severe delays on Piccadilly line",
            ["piccadilly"],
            "",
        ),
        (
            "2026-04-22-VIC-001",
            "2026-04-22T07:00:00+00:00",  # last_update -- middle
            "Change of frequency on Victoria line",
            ["victoria"],
            "",
        ),
        (
            "2026-04-21-VIC-001",
            "2026-04-21T09:00:00+00:00",  # last_update -- oldest
            "Engineering works affecting Victoria line weekend service",
            ["victoria"],
            "No service between Seven Sisters and Walthamstow Central on Sunday.",
        ),
    ]
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for disruption_id, last_update, summary, affected_routes, closure_text in rows:
                cur.execute(
                    """
                    INSERT INTO analytics.stg_disruptions (
                        event_id, ingested_at, event_type, source,
                        disruption_id, category, category_description,
                        description, summary, closure_text, severity,
                        created, last_update, affected_routes, affected_stops
                    ) VALUES (
                        gen_random_uuid(), now(), %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s::jsonb, %s::jsonb
                    )
                    """,
                    (
                        "disruptions.snapshot",
                        MARKER,
                        disruption_id,
                        "RealTime",
                        "Real Time",
                        f"Description for {disruption_id}",
                        summary,
                        closure_text if closure_text else None,
                        6,
                        "2026-04-21T00:00:00+00:00",
                        last_update,
                        json.dumps(affected_routes),
                        json.dumps([]),
                    ),
                )
        conn.commit()

    with TestClient(app) as client:
        response = client.get("/api/v1/disruptions/recent", params={"limit": 10})

    assert response.status_code == 200
    body = response.json()
    # We seeded 3, but other test runs / dbt may have left rows behind;
    # filter to the marker by disruption_id prefix.
    seeded_ids = {"2026-04-22-PIC-001", "2026-04-22-VIC-001", "2026-04-21-VIC-001"}
    seen_ids = [item["disruption_id"] for item in body if item["disruption_id"] in seeded_ids]
    assert seen_ids == [
        "2026-04-22-PIC-001",
        "2026-04-22-VIC-001",
        "2026-04-21-VIC-001",
    ]
    # closure_text from the third row was NULL upstream; SQL coalesces
    # to empty string before it lands in the response.
    closure_lookup = {item["disruption_id"]: item["closure_text"] for item in body}
    assert closure_lookup["2026-04-22-PIC-001"] == ""
    assert closure_lookup["2026-04-21-VIC-001"].startswith("No service between")
