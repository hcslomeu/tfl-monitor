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
