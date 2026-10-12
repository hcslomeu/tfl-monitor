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
) -> None:
    client = fake_tfl_client_factory(
        disruptions=[_disrupted_line("piccadilly"), _disrupted_line("victoria")]
    )
    attach_tfl_client(client)

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, s-maxage=30, stale-while-revalidate=30"
    body = response.json()
    assert {item["affected_routes"][0] for item in body} == {"piccadilly", "victoria"}
    assert client.disruption_calls == [DEFAULT_STATUS_MODES]


def test_returns_empty_list_when_no_disruptions(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
) -> None:
    attach_tfl_client(fake_tfl_client_factory(disruptions=[]))

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 200
    assert response.json() == []


def test_mode_filter_scopes_the_tfl_query(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
) -> None:
    client = fake_tfl_client_factory(disruptions=[])
    attach_tfl_client(client)

    TestClient(app).get("/api/v1/disruptions/recent", params={"mode": "tube"})

    assert client.disruption_calls == [("tube",)]


def test_custom_limit_truncates_results(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
) -> None:
    client = fake_tfl_client_factory(
        disruptions=[_disrupted_line("piccadilly"), _disrupted_line("victoria")]
    )
    attach_tfl_client(client)

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

    response = TestClient(app).get("/api/v1/disruptions/recent")

    body = response.json()
    assert body[0]["closure_text"].startswith("No service between Seven Sisters")


def test_affected_stops_resolved_via_tfl_stop_points(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
) -> None:
    client = fake_tfl_client_factory(
        disruptions=[_disrupted_line("piccadilly", affected_stops=["940GZZLUOXC", "940GZZLUHBN"])],
        stop_names={"940GZZLUOXC": "Oxford Circus", "940GZZLUHBN": "Holborn"},
    )
    attach_tfl_client(client)

    response = TestClient(app).get("/api/v1/disruptions/recent")

    body = response.json()
    assert {(s["naptan_id"], s["name"]) for s in body[0]["affected_stops"]} == {
        ("940GZZLUOXC", "Oxford Circus"),
        ("940GZZLUHBN", "Holborn"),
    }


def test_affected_stops_unmatched_surface_name_none(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
) -> None:
    """A NaPTAN TfL cannot resolve surfaces name=None."""
    client = fake_tfl_client_factory(
        disruptions=[_disrupted_line("piccadilly", affected_stops=["940GZZLUOXC", "490UNKNOWN"])],
        stop_names={"940GZZLUOXC": "Oxford Circus"},
    )
    attach_tfl_client(client)

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


def test_tfl_upstream_failure_returns_502(
    fake_tfl_client_factory: Callable[..., Any],
    attach_tfl_client: Callable[[Any], None],
) -> None:
    attach_tfl_client(fake_tfl_client_factory(fail=True))

    response = TestClient(app).get("/api/v1/disruptions/recent")

    assert response.status_code == 502
    assert "cache-control" not in response.headers
    body = response.json()
    assert body["status"] == 502
    assert body["title"] == "Bad Gateway"
