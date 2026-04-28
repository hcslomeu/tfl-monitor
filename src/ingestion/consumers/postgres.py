"""Postgres writer for ``raw.line_status``."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Self

import logfire
import psycopg
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from contracts.schemas.line_status import LineStatusEvent

__all__ = ["INSERT_RAW_LINE_STATUS_SQL", "RawLineStatusWriter"]

INSERT_RAW_LINE_STATUS_SQL = """
INSERT INTO raw.line_status (event_id, ingested_at, event_type, source, payload)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (event_id) DO NOTHING
"""

_RECONNECT_BACKOFF_SECONDS = 1.0

ConnectionFactory = Callable[[str], Awaitable[AsyncConnection]]


async def _default_connection_factory(dsn: str) -> AsyncConnection:
    return await psycopg.AsyncConnection.connect(dsn, autocommit=True)


class RawLineStatusWriter:
    """Owns a single async psycopg connection; reconnects on transient errors."""

    def __init__(
        self,
        dsn: str,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        if not dsn:
            raise ValueError("dsn must be a non-empty string")
        self._dsn = dsn
        self._connection_factory = connection_factory or _default_connection_factory
        self._conn: AsyncConnection | None = None

    async def __aenter__(self) -> Self:
        self._conn = await self._connection_factory(self._dsn)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._close()

    async def insert(self, event: LineStatusEvent) -> int:
        """Insert one envelope; returns ``rowcount`` (1 = inserted, 0 = duplicate)."""
        conn = self._require_connection()
        params = (
            event.event_id,
            event.ingested_at,
            event.event_type,
            event.source,
            Jsonb(event.payload.model_dump(mode="json")),
        )
        with logfire.span(
            "db.insert",
            table="raw.line_status",
            event_id=str(event.event_id),
        ) as span:
            cursor = await conn.execute(INSERT_RAW_LINE_STATUS_SQL, params)
            rowcount = cursor.rowcount
            span.set_attribute("rowcount", rowcount)
            return rowcount

    async def reconnect(self) -> None:
        """Close + reopen the connection. Used after ``OperationalError``."""
        await self._close()
        await asyncio.sleep(_RECONNECT_BACKOFF_SECONDS)
        self._conn = await self._connection_factory(self._dsn)

    async def _close(self) -> None:
        if self._conn is None:
            return
        try:
            await self._conn.close()
        except Exception as exc:  # noqa: BLE001 - best-effort close
            logfire.warn(
                "ingestion.line_status.db_close_failed",
                error=repr(exc),
            )
        finally:
            self._conn = None

    def _require_connection(self) -> AsyncConnection:
        if self._conn is None:
            raise RuntimeError(
                "RawLineStatusWriter is not active; use it as 'async with RawLineStatusWriter(...)'"
            )
        return self._conn
