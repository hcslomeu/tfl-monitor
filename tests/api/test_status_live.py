"""Unit tests for the ``/api/v1/status/live`` endpoint (live TfL read-through)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from api.main import app
from contracts.schemas.tfl_api import TflLineResponse, TflLineStatusItem, TflValidityPeriod


def _line(
    line_id: str,
    *,
    mode: str = "tube",
    statuses: list[TflLineStatusItem] | None = None,
) -> TflLineResponse:
    if statuses is None:
        statuses = [
            TflLineStatusItem(status_severity=10, status_severity_description="Good Service")
        ]
    return TflLineResponse(
        id=line_id,
        name=line_id.title(),
        mode_name=mode,
        line_statuses=statuses,
    )


def _status(severity: int, description: str) -> TflLineStatusItem:
    return TflLineStatusItem(status_severity=severity, status_severity_description=description)


def test_returns_one_row_per_line(
    fake_tfl_client_factory: Callable[..., Any], attach_tfl_client: Callable[[Any], None]
) -> None:
    client = fake_tfl_client_factory(
        line_statuses=[
            _line("piccadilly", statuses=[_status(6, "Severe Delays")]),
            _line("victoria"),
        ]
    )
    attach_tfl_client(client)

    response = TestClient(app).get("/api/v1/status/live")

    assert response.status_code == 200
    body = response.json()
    assert {item["line_id"] for item in body} == {"piccadilly", "victoria"}
    pic = next(item for item in body if item["line_id"] == "piccadilly")
    assert pic["status_severity"] == 6
    assert client.status_calls, "expected fetch_line_statuses to be called"


def test_skips_lines_with_unknown_mode(
    fake_tfl_client_factory: Callable[..., Any], attach_tfl_client: Callable[[Any], None]
) -> None:
    client = fake_tfl_client_factory(
        line_statuses=[_line("space-lift", mode="space-elevator"), _line("victoria")]
    )
    attach_tfl_client(client)

    response = TestClient(app).get("/api/v1/status/live")

    assert response.status_code == 200
    assert [item["line_id"] for item in response.json()] == ["victoria"]


def test_primary_status_prefers_disruption_over_good_service(
    fake_tfl_client_factory: Callable[..., Any], attach_tfl_client: Callable[[Any], None]
) -> None:
    """A line carrying both Good Service and a disruption surfaces the disruption."""
    client = fake_tfl_client_factory(
        line_statuses=[
            _line(
                "district",
                statuses=[_status(10, "Good Service"), _status(6, "Severe Delays")],
            )
        ]
    )
    attach_tfl_client(client)

    response = TestClient(app).get("/api/v1/status/live")

    body = response.json()
    assert body[0]["status_severity"] == 6
    assert body[0]["status_severity_description"] == "Severe Delays"


def test_fallback_validity_window_when_no_periods(
    fake_tfl_client_factory: Callable[..., Any], attach_tfl_client: Callable[[Any], None]
) -> None:
    """A status with no validity periods still yields a from/to window."""
    client = fake_tfl_client_factory(line_statuses=[_line("victoria")])
    attach_tfl_client(client)

    response = TestClient(app).get("/api/v1/status/live")

    item = response.json()[0]
    assert item["valid_from"]
    assert item["valid_to"]


def test_uses_declared_validity_period_when_present(
    fake_tfl_client_factory: Callable[..., Any], attach_tfl_client: Callable[[Any], None]
) -> None:
    status = _status(9, "Minor Delays")
    status = status.model_copy(
        update={
            "validity_periods": [
                TflValidityPeriod(
                    from_date="2026-04-28T06:00:00Z",
                    to_date="2026-04-28T23:59:00Z",
                    is_now=True,
                )
            ]
        }
    )
    client = fake_tfl_client_factory(line_statuses=[_line("victoria", statuses=[status])])
    attach_tfl_client(client)

    response = TestClient(app).get("/api/v1/status/live")

    item = response.json()[0]
    assert item["valid_from"].startswith("2026-04-28T06:00")


def test_empty_result_returns_empty_list(
    fake_tfl_client_factory: Callable[..., Any], attach_tfl_client: Callable[[Any], None]
) -> None:
    attach_tfl_client(fake_tfl_client_factory(line_statuses=[]))

    response = TestClient(app).get("/api/v1/status/live")

    assert response.status_code == 200
    assert response.json() == []


def test_missing_tfl_client_returns_503(attach_tfl_client: Callable[[Any], None]) -> None:
    attach_tfl_client(None)

    response = TestClient(app).get("/api/v1/status/live")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 503
    assert body["title"] == "Service Unavailable"
    assert "TfL client" in body["detail"]
