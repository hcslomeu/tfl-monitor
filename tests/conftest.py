"""Shared pytest fixtures for the API unit tests.

Provides a minimal in-memory stand-in for ``psycopg_pool.AsyncConnectionPool``
so handlers can be exercised without a live Postgres. The fakes record every
``(sql, params)`` pair so tests can assert on the query the handler issued
in addition to the JSON response shape.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class FakeAsyncCursor:
    """Async cursor that returns canned rows and records executed SQL."""

    rows: list[Any]
    executed: list[tuple[str, dict[str, Any] | None]]

    async def __aenter__(self) -> FakeAsyncCursor:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.executed.append((sql, params))

    async def fetchall(self) -> list[Any]:
        return list(self.rows)

    async def fetchone(self) -> Any | None:
        return self.rows[0] if self.rows else None


@dataclass
class FakeAsyncConnection:
    """Async connection that hands out cursors backed by primed batches.

    ``batches`` is consumed in order: each ``cursor()`` call pops the next
    batch of rows. Tests prime as many batches as the handler is expected
    to issue queries.
    """

    batches: list[list[Any]]
    executed: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)

    def cursor(self, *, row_factory: Any = None) -> FakeAsyncCursor:
        rows = self.batches.pop(0) if self.batches else []
        return FakeAsyncCursor(rows=rows, executed=self.executed)


@dataclass
class FakeAsyncPool:
    """Stand-in for ``AsyncConnectionPool`` with a single recorded connection."""

    conn: FakeAsyncConnection

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[FakeAsyncConnection]:
        yield self.conn

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.fixture
def fake_pool_factory() -> Any:
    """Return a callable that builds a ``FakeAsyncPool`` from row batches."""

    def _factory(*batches: list[Any]) -> FakeAsyncPool:
        return FakeAsyncPool(conn=FakeAsyncConnection(batches=list(batches)))

    return _factory


@pytest.fixture
def attach_pool() -> Iterator[Any]:
    """Attach a fake pool to ``app.state.db_pool`` and restore on teardown."""
    from api.main import app

    original = app.state.db_pool

    def _attach(pool: Any) -> None:
        app.state.db_pool = pool

    try:
        yield _attach
    finally:
        app.state.db_pool = original


@dataclass
class FakeTflClient:
    """Stand-in for ``TflClient`` returning canned tier-1 line responses.

    ``fetch_stop_point`` always raises ``TflClientError`` so the station
    resolver's TfL fallback resolves to ``None`` (unit tests resolve
    matched NaPTANs through the primed dim_stations pool batch instead).
    """

    line_statuses: list[Any] = field(default_factory=list)
    disruptions: list[Any] = field(default_factory=list)
    fail: bool = False
    status_calls: list[tuple[str, ...]] = field(default_factory=list)
    disruption_calls: list[tuple[str, ...]] = field(default_factory=list)

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

        raise TflClientError(f"no stop point for {naptan_id}")


@pytest.fixture
def fake_tfl_client_factory() -> Any:
    """Return a callable building a ``FakeTflClient`` from canned responses."""

    def _factory(
        *,
        line_statuses: list[Any] | None = None,
        disruptions: list[Any] | None = None,
        fail: bool = False,
    ) -> FakeTflClient:
        return FakeTflClient(
            line_statuses=line_statuses or [],
            disruptions=disruptions or [],
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
