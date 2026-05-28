"""Unit tests for the ``/api/v1/disruptions/recent`` endpoint (live TfL read-through)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from api.live import DEFAULT_STATUS_MODES
from api.main import app
from contracts.schemas.tfl_api import (
    TflLineResponse,
    TflLineStatusDisruption,
    TflLineStatusItem,
)


def _disrupted_line(
    line_id: str,
    *,
    category: str = "RealTime",
    description: str | None = None,
    closure_text: str = "",
    affected_stops: list[str] | None = None,
) -> TflLineResponse:
    disruption = TflLineStatusDisruption(
        category=category,
        category_description=category,
        description=description or f"Description for {line_id}",
        closure_text=closure_text or None,
        affected_stops=[{"naptanId": nid} for nid in (affected_stops or [])],
    )
    return TflLineResponse(
        id=line_id,
        name=line_id.title(),
        mode_name="tube",
        line_statuses=[
            TflLineStatusItem(
                status_severity=6,
                status_severity_description="Severe Delays",
                disruption=disruption,
            )
        ],
    )


def test_happy_path_default_limit_and_modes(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
    fake_pool_factory: Callable[..., Any],
    attach_pool: Callable[[Any], None],
) -> None:
    client = fake_tfl_client_factory(
        disruptions=[_disrupted_line("piccadilly"), _disrupted_line("victoria")]
    )
    attach_tfl_client(client)
    attach_pool(fake_pool_factory([]))

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 200
    body = response.json()
    assert {item["affected_routes"][0] for item in body} == {"piccadilly", "victoria"}
    assert client.disruption_calls == [DEFAULT_STATUS_MODES]


def test_returns_empty_list_when_no_disruptions(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
    fake_pool_factory: Callable[..., Any],
    attach_pool: Callable[[Any], None],
) -> None:
    attach_tfl_client(fake_tfl_client_factory(disruptions=[]))
    attach_pool(fake_pool_factory([]))

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 200
    assert response.json() == []


def test_mode_filter_scopes_the_tfl_query(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
    fake_pool_factory: Callable[..., Any],
    attach_pool: Callable[[Any], None],
) -> None:
    client = fake_tfl_client_factory(disruptions=[])
    attach_tfl_client(client)
    attach_pool(fake_pool_factory([]))

    TestClient(app).get("/api/v1/disruptions/recent", params={"mode": "tube"})

    assert client.disruption_calls == [("tube",)]


def test_custom_limit_truncates_results(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
    fake_pool_factory: Callable[..., Any],
    attach_pool: Callable[[Any], None],
) -> None:
    client = fake_tfl_client_factory(
        disruptions=[_disrupted_line("piccadilly"), _disrupted_line("victoria")]
    )
    attach_tfl_client(client)
    attach_pool(fake_pool_factory([]))

    response = TestClient(app).get("/api/v1/disruptions/recent", params={"limit": 1})

    assert len(response.json()) == 1


def test_invalid_mode_returns_422(
    fake_tfl_client_factory: Callable[..., Any], attach_tfl_client: Callable[[Any], None]
) -> None:
    attach_tfl_client(fake_tfl_client_factory())
    response = TestClient(app).get("/api/v1/disruptions/recent", params={"mode": "spaceship"})
    assert response.status_code == 422


def test_limit_below_min_returns_422(
    fake_tfl_client_factory: Callable[..., Any], attach_tfl_client: Callable[[Any], None]
) -> None:
    attach_tfl_client(fake_tfl_client_factory())
    response = TestClient(app).get("/api/v1/disruptions/recent", params={"limit": 0})
    assert response.status_code == 422


def test_limit_above_max_returns_422(
    fake_tfl_client_factory: Callable[..., Any], attach_tfl_client: Callable[[Any], None]
) -> None:
    attach_tfl_client(fake_tfl_client_factory())
    response = TestClient(app).get("/api/v1/disruptions/recent", params={"limit": 201})
    assert response.status_code == 422


def test_closure_text_passes_through_as_string(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
    fake_pool_factory: Callable[..., Any],
    attach_pool: Callable[[Any], None],
) -> None:
    client = fake_tfl_client_factory(
        disruptions=[
            _disrupted_line(
                "victoria",
                closure_text="No service between Seven Sisters and Walthamstow Central.",
            )
        ]
    )
    attach_tfl_client(client)
    attach_pool(fake_pool_factory([]))

    response = TestClient(app).get("/api/v1/disruptions/recent")

    body = response.json()
    assert body[0]["closure_text"].startswith("No service between Seven Sisters")


def test_affected_stops_resolved_via_dim_stations(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
    fake_pool_factory: Callable[..., Any],
    attach_pool: Callable[[Any], None],
) -> None:
    client = fake_tfl_client_factory(
        disruptions=[_disrupted_line("piccadilly", affected_stops=["940GZZLUOXC", "940GZZLUHBN"])]
    )
    attach_tfl_client(client)
    attach_pool(
        fake_pool_factory(
            [
                {"naptan_id": "940GZZLUOXC", "name": "Oxford Circus"},
                {"naptan_id": "940GZZLUHBN", "name": "Holborn"},
            ]
        )
    )

    response = TestClient(app).get("/api/v1/disruptions/recent")

    body = response.json()
    assert {(s["naptan_id"], s["name"]) for s in body[0]["affected_stops"]} == {
        ("940GZZLUOXC", "Oxford Circus"),
        ("940GZZLUHBN", "Holborn"),
    }


def test_affected_stops_unmatched_surface_name_none(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
    fake_pool_factory: Callable[..., Any],
    attach_pool: Callable[[Any], None],
) -> None:
    """A NaPTAN absent from dim_stations (and TfL fallback) surfaces name=None."""
    client = fake_tfl_client_factory(
        disruptions=[_disrupted_line("piccadilly", affected_stops=["940GZZLUOXC", "490UNKNOWN"])]
    )
    attach_tfl_client(client)
    attach_pool(fake_pool_factory([{"naptan_id": "940GZZLUOXC", "name": "Oxford Circus"}]))

    response = TestClient(app).get("/api/v1/disruptions/recent")

    body = response.json()
    by_naptan = {s["naptan_id"]: s["name"] for s in body[0]["affected_stops"]}
    assert by_naptan == {"940GZZLUOXC": "Oxford Circus", "490UNKNOWN": None}


def test_missing_tfl_client_returns_503(attach_tfl_client: Callable[[Any], None]) -> None:
    attach_tfl_client(None)

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == 503
    assert "TfL client" in body["detail"]


def test_missing_pool_returns_503(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
    attach_pool: Callable[[Any], None],
) -> None:
    attach_tfl_client(fake_tfl_client_factory())
    attach_pool(None)

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 503
    assert response.json()["status"] == 503


def test_tfl_upstream_failure_returns_502(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
    fake_pool_factory: Callable[..., Any],
    attach_pool: Callable[[Any], None],
) -> None:
    attach_tfl_client(fake_tfl_client_factory(fail=True))
    attach_pool(fake_pool_factory([]))

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 502
    body = response.json()
    assert body["status"] == 502
    assert body["title"] == "Bad Gateway"
