"""CORS allow-list tests for the public API.

Locks the four behaviours required by TM-F2 plan §3.1:

- ``http://localhost:3000`` (dev origin) is echoed via the pinned list.
- ``https://tfl-monitor.humbertolomeu.com`` (apex) is echoed via the pinned list.
- A representative Vercel preview origin matches the regex and is echoed.
- ``https://tfl-monitor.vercel.app.attacker.com`` is rejected because the
  regex is anchored — proves the negative so a future regex edit cannot
  silently widen the allow-list.

Tests issue a CORS preflight (``OPTIONS`` + ``Origin`` + ``Access-Control-Request-Method``)
because ``CORSMiddleware`` short-circuits preflight requests without touching the
DB pool, so they exercise the middleware in isolation without any fakes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


def _preflight(origin: str) -> tuple[int, str | None]:
    response = TestClient(app).options(
        "/api/v1/status/live",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    return response.status_code, response.headers.get("access-control-allow-origin")


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "https://tfl-monitor.humbertolomeu.com",
        "https://tfl-monitor.vercel.app",
        "https://tfl-monitor-abc123-humberto.vercel.app",
        "https://tfl-monitor-pr-42-team.vercel.app",
    ],
)
def test_allowed_origin_is_echoed(origin: str) -> None:
    status, echoed = _preflight(origin)
    assert status == 200, f"expected 200 for {origin}, got {status}"
    assert echoed == origin, f"expected echo for {origin}, got {echoed!r}"


@pytest.mark.parametrize(
    "origin",
    [
        "https://tfl-monitor.vercel.app.attacker.com",
        "https://attacker.com",
        "http://tfl-monitor.humbertolomeu.com",
        "https://tfl-monitor-abc.vercel.app.attacker.com",
        "https://evil-tfl-monitor-abc.vercel.app",
    ],
)
def test_disallowed_origin_is_not_echoed(origin: str) -> None:
    _, echoed = _preflight(origin)
    assert echoed != origin, f"middleware unexpectedly echoed {origin!r}"
