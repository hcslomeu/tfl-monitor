"""Lock the 501 stubs and detect drift between FastAPI routes and the OpenAPI spec.

Until the owning work packages (TM-D2, TM-D3, TM-D5) wire the real handlers,
every non-``/health`` route must return ``501 Not Implemented`` with a
detail that points to the WP that will implement it. This file also asserts
that the FastAPI surface and ``contracts/openapi.yaml`` agree on the set of
operation IDs in both directions, so neither side can drift silently.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from openapi_spec_validator.readers import read_from_filename

from api.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = REPO_ROOT / "contracts" / "openapi.yaml"

# FastAPI registers a few routes for the auto-generated docs. They are not in
# our hand-written spec, so the App→Spec direction must ignore them.
FASTAPI_BUILTIN_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


# (method, path, body, expected_wp_hint)
StubCase = tuple[str, str, dict[str, Any] | None, str]

STUB_ROUTES: list[StubCase] = [
    ("POST", "/api/v1/chat/stream", {"thread_id": "t-1", "message": "hi"}, "TM-D5"),
    ("GET", "/api/v1/chat/t-1/history", None, "TM-D5"),
]


def _api_routes(app_obj: Any) -> Iterable[APIRoute]:
    """Yield only the user-defined ``APIRoute`` instances on the FastAPI app."""
    for route in app_obj.routes:
        if isinstance(route, APIRoute):
            yield route


def _spec_operation_ids(spec: dict[str, Any]) -> set[str]:
    """Collect every ``operationId`` declared under ``paths`` in the OpenAPI spec."""
    operation_ids: set[str] = set()
    for path_item in spec["paths"].values():
        for operation in path_item.values():
            if isinstance(operation, dict) and "operationId" in operation:
                operation_ids.add(operation["operationId"])
    return operation_ids


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def openapi_spec() -> dict[str, Any]:
    spec, _base_uri = read_from_filename(str(OPENAPI_PATH))
    assert isinstance(spec, dict)
    return spec


@pytest.mark.parametrize(("method", "path", "body", "wp_hint"), STUB_ROUTES)
def test_stub_returns_501(
    client: TestClient,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    wp_hint: str,
) -> None:
    """Every non-``/health`` route must 501 with its owning-WP hint until landed."""
    response = client.request(method, path, json=body)
    assert response.status_code == 501, (
        f"{method} {path} expected 501, got {response.status_code}: {response.text}"
    )
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert detail.startswith("Not implemented"), detail
    assert wp_hint in detail, f"expected {wp_hint!r} in detail, got {detail!r}"


def test_every_app_route_declares_operation_id() -> None:
    """Guard against silent drift: every user-defined route needs an ``operationId``.

    Without this, a developer could add a route, forget to set ``operation_id``,
    and the App→Spec drift test would still pass because the route would be
    invisible to the comparison.
    """
    routes_missing_id = sorted(
        f"{','.join(sorted(route.methods or set()))} {route.path}"
        for route in _api_routes(app)
        if route.path not in FASTAPI_BUILTIN_PATHS and not route.operation_id
    )
    assert not routes_missing_id, (
        f"FastAPI routes without an operation_id (drift test would silently skip them): "
        f"{routes_missing_id}"
    )


def test_spec_operation_ids_have_matching_routes(openapi_spec: dict[str, Any]) -> None:
    """Every ``operationId`` in the OpenAPI spec must exist as a FastAPI route."""
    spec_operation_ids = _spec_operation_ids(openapi_spec)
    app_operation_ids = {route.operation_id for route in _api_routes(app) if route.operation_id}

    missing_in_app = spec_operation_ids - app_operation_ids
    assert not missing_in_app, (
        f"operationIds declared in contracts/openapi.yaml but missing from app: "
        f"{sorted(missing_in_app)}"
    )


def test_app_routes_have_matching_spec_entries(openapi_spec: dict[str, Any]) -> None:
    """Every FastAPI route must have a matching ``operationId`` in the spec.

    The companion ``test_every_app_route_declares_operation_id`` check
    guarantees no route reaches this point with a falsy ``operation_id``,
    so the set subtraction can never produce a ``None`` element.
    """
    spec_operation_ids = _spec_operation_ids(openapi_spec)
    app_operation_ids = {
        route.operation_id
        for route in _api_routes(app)
        if route.operation_id and route.path not in FASTAPI_BUILTIN_PATHS
    }

    missing_in_spec = app_operation_ids - spec_operation_ids
    assert not missing_in_spec, (
        f"FastAPI routes without a matching operationId in contracts/openapi.yaml: "
        f"{sorted(missing_in_spec)}"
    )
