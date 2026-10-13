"""Shared pytest fixtures for the API unit tests.

Provides in-memory stand-ins for the TfL client and the compiled agent so
handlers can be exercised without network access or an LLM.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest


@dataclass
class FakeTflClient:
    """Stand-in for ``TflClient`` returning canned tier-1 line responses.

    ``fetch_stop_point`` returns a stop point named from ``stop_names``
    and raises ``TflClientError`` for any other NaPTAN, so unmatched
    codes resolve to ``None``.
    """

    line_statuses: list[Any] = field(default_factory=list)
    disruptions: list[Any] = field(default_factory=list)
    stop_names: dict[str, str] = field(default_factory=dict)
    fail: bool = False
    status_calls: list[tuple[str, ...]] = field(default_factory=list)
    disruption_calls: list[tuple[str, ...]] = field(default_factory=list)
    stop_point_calls: list[str] = field(default_factory=list)

    async def fetch_line_statuses(self, modes: Any) -> list[Any]:
        self.status_calls.append(tuple(modes))
        if self.fail:
            raise RuntimeError("TfL upstream failure")
        return list(self.line_statuses)

    async def fetch_line_disruptions(self, modes: Any) -> list[Any]:
        self.disruption_calls.append(tuple(modes))
        if self.fail:
            raise RuntimeError("TfL upstream failure")
        return list(self.disruptions)

    async def fetch_stop_point(self, naptan_id: str) -> Any:
        from ingestion.tfl_client.retry import TflClientError

        self.stop_point_calls.append(naptan_id)
        if naptan_id in self.stop_names:
            return SimpleNamespace(common_name=self.stop_names[naptan_id])
        raise TflClientError(f"no stop point for {naptan_id}")


@pytest.fixture
def fake_tfl_client_factory() -> Any:
    """Return a callable building a ``FakeTflClient`` from canned responses."""

    def _factory(
        *,
        line_statuses: list[Any] | None = None,
        disruptions: list[Any] | None = None,
        stop_names: dict[str, str] | None = None,
        fail: bool = False,
    ) -> FakeTflClient:
        return FakeTflClient(
            line_statuses=line_statuses or [],
            disruptions=disruptions or [],
            stop_names=stop_names or {},
            fail=fail,
        )

    return _factory


@pytest.fixture
def attach_tfl_client() -> Iterator[Any]:
    """Attach a fake TfL client to ``app.state.tfl_client`` and restore on teardown."""
    from api.main import app

    original = getattr(app.state, "tfl_client", None)

    def _attach(client: Any) -> None:
        app.state.tfl_client = client

    try:
        yield _attach
    finally:
        app.state.tfl_client = original


@pytest.fixture
def attach_agent() -> Iterator[Any]:
    """Attach a fake agent to ``app.state.agent`` and restore on teardown."""
    from api.main import app

    original = getattr(app.state, "agent", None)

    def _attach(agent: Any) -> None:
        app.state.agent = agent

    try:
        yield _attach
    finally:
        app.state.agent = original


@pytest.fixture(autouse=True)
def _clear_stations_cache() -> Iterator[None]:
    """Reset the process-lifetime NaPTAN cache between tests.

    ``api.stations`` keeps a module-level dict for cross-request reuse,
    which would otherwise leak resolved (or unresolved) NaPTAN entries
    between unit tests and make assertion ordering brittle.
    """
    from api import stations

    stations._cache_clear()  # noqa: SLF001
    try:
        yield
    finally:
        stations._cache_clear()  # noqa: SLF001
