"""Unit tests for the ``/api/v1/disruptions/recent`` endpoint."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from api.db import DISRUPTIONS_SQL
from api.main import app


def _row(
    disruption_id: str,
    *,
    last_update: datetime | None = None,
    closure_text: str = "",
    affected_routes: list[str] | None = None,
    affected_stops: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "disruption_id": disruption_id,
        "category": "RealTime",
        "category_description": "Real Time",
        "description": f"Description for {disruption_id}",
        "summary": f"Summary for {disruption_id}",
        "affected_routes": affected_routes if affected_routes is not None else ["victoria"],
        "affected_stops": affected_stops if affected_stops is not None else [],
        "closure_text": closure_text,
        "severity": 6,
        "created": datetime(2026, 4, 22, 6, 0, tzinfo=UTC),
        "last_update": last_update or datetime(2026, 4, 22, 8, 0, tzinfo=UTC),
    }


def test_happy_path_default_limit(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory(
        [
            _row("2026-04-22-PIC-001", last_update=datetime(2026, 4, 22, 8, 5, tzinfo=UTC)),
            _row("2026-04-22-VIC-001", last_update=datetime(2026, 4, 22, 7, 0, tzinfo=UTC)),
        ]
    )
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 200
    body = response.json()
    assert [item["disruption_id"] for item in body] == [
        "2026-04-22-PIC-001",
        "2026-04-22-VIC-001",
    ]
    sql, params = pool.conn.executed[0]
    assert sql == DISRUPTIONS_SQL
    assert params == {"limit": 50, "mode": None}


def test_returns_empty_list_when_no_rows(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory([])
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 200
    assert response.json() == []


def test_mode_filter_passes_through(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory([])
    attach_pool(pool)

    TestClient(app).get("/api/v1/disruptions/recent", params={"mode": "tube"})

    _sql, params = pool.conn.executed[0]
    assert params is not None
    assert params["mode"] == "tube"


def test_custom_limit_passes_through(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    pool = fake_pool_factory([])
    attach_pool(pool)

    TestClient(app).get("/api/v1/disruptions/recent", params={"limit": 25})

    _sql, params = pool.conn.executed[0]
    assert params is not None
    assert params["limit"] == 25


def test_invalid_mode_returns_422(attach_pool: Callable[[Any], None]) -> None:
    response = TestClient(app).get("/api/v1/disruptions/recent", params={"mode": "spaceship"})
    assert response.status_code == 422


def test_limit_below_min_returns_422(attach_pool: Callable[[Any], None]) -> None:
    response = TestClient(app).get("/api/v1/disruptions/recent", params={"limit": 0})
    assert response.status_code == 422


def test_limit_above_max_returns_422(attach_pool: Callable[[Any], None]) -> None:
    response = TestClient(app).get("/api/v1/disruptions/recent", params={"limit": 201})
    assert response.status_code == 422


def test_closure_text_passes_through_as_string(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    """SQL ``COALESCE(closure_text, '')`` guarantees a string lands here."""
    pool = fake_pool_factory(
        [
            _row(
                "2026-04-21-VIC-001",
                closure_text="No service between Seven Sisters and Walthamstow Central.",
            )
        ]
    )
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["closure_text"].startswith("No service between Seven Sisters")


def test_jsonb_arrays_deserialise_to_lists(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    """affected_routes round-trips as a list of strings; affected_stops
    surfaces as ``AffectedStop`` objects with ``name=None`` when the
    dim_stations seed has no match (here: empty seed batch primed)."""
    pool = fake_pool_factory(
        [
            _row(
                "2026-04-22-PIC-001",
                affected_routes=["piccadilly", "victoria"],
                affected_stops=["940GZZLUATN", "940GZZLUACT"],
            )
        ],
        [],
    )
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["affected_routes"] == ["piccadilly", "victoria"]
    assert body[0]["affected_stops"] == [
        {"naptan_id": "940GZZLUATN", "name": None},
        {"naptan_id": "940GZZLUACT", "name": None},
    ]


def test_affected_stops_resolved_via_dim_stations(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    """When the dim_stations seed matches a NaPTAN, the response
    surfaces the human-readable name alongside the original code."""
    pool = fake_pool_factory(
        [
            _row(
                "2026-04-22-PIC-001",
                affected_stops=["940GZZLUOXC", "940GZZLUHBN"],
            )
        ],
        [
            {"naptan_id": "940GZZLUOXC", "name": "Oxford Circus"},
            {"naptan_id": "940GZZLUHBN", "name": "Holborn"},
        ],
    )
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 200
    body = response.json()
    assert {(s["naptan_id"], s["name"]) for s in body[0]["affected_stops"]} == {
        ("940GZZLUOXC", "Oxford Circus"),
        ("940GZZLUHBN", "Holborn"),
    }


def test_affected_stops_partial_seed_match_keeps_naptan_for_misses(
    fake_pool_factory: Callable[..., Any], attach_pool: Callable[[Any], None]
) -> None:
    """A NaPTAN absent from dim_stations and without a TfL fallback
    surfaces as ``name=None`` so the frontend can show the raw code."""
    pool = fake_pool_factory(
        [
            _row(
                "2026-04-22-PIC-001",
                affected_stops=["940GZZLUOXC", "490UNKNOWN"],
            )
        ],
        [{"naptan_id": "940GZZLUOXC", "name": "Oxford Circus"}],
    )
    attach_pool(pool)

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 200
    body = response.json()
    by_naptan = {s["naptan_id"]: s["name"] for s in body[0]["affected_stops"]}
    assert by_naptan == {"940GZZLUOXC": "Oxford Circus", "490UNKNOWN": None}


def test_missing_pool_returns_503(attach_pool: Callable[[Any], None]) -> None:
    attach_pool(None)

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 503
    assert body["title"] == "Service Unavailable"


def test_disruptions_sql_casts_mode_to_text_at_every_occurrence() -> None:
    """Regression guard: both ``%(mode)s`` binds must carry ``::text``.

    Supabase's pgbouncer pooler refuses ``%(mode)s IS NULL`` without an
    inline cast (``psycopg.errors.AmbiguousParameter``), so the fix that
    closed the production outage cast both binds to ``::text``. This
    test fails fast if either cast is dropped — the existing tests
    assert ``sql == DISRUPTIONS_SQL`` against the constant itself, so
    they would silently track any regression in the constant's body.
    """
    assert "%(mode)s::text IS NULL" in DISRUPTIONS_SQL
    assert "sls.mode = %(mode)s::text" in DISRUPTIONS_SQL
    # Belt-and-braces: the bare un-cast forms must not reappear.
    assert "%(mode)s IS NULL" not in DISRUPTIONS_SQL.replace("%(mode)s::text IS NULL", "")
    assert "sls.mode = %(mode)s\n" not in DISRUPTIONS_SQL
