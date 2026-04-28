"""Postgres writer for ``raw.<topic>`` envelope tables.

Generalises TM-B3's line-status-specific writer into a single
parameterised class that supports every raw envelope table declared
in ``contracts/sql/001_raw_tables.sql``: ``raw.line_status``,
``raw.arrivals``, ``raw.disruptions``. The DDL is identical across
all three (5-column envelope + JSONB payload), so the only inputs
that differ are the table name and the event class.

The ``table`` parameter is validated against an allow-list to keep
SQL injection out of the format-string substitution; bound values
remain parameterised via ``%s`` (CLAUDE.md §"Security-first").
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Self

import logfire
import psycopg
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from contracts.schemas.common import Event

__all__ = [
    "ALLOWED_RAW_TABLES",
    "INSERT_RAW_EVENT_SQL_TEMPLATE",
    "RawEventWriter",
]

INSERT_RAW_EVENT_SQL_TEMPLATE = (
    "INSERT INTO {table} (event_id, ingested_at, event_type, source, payload) "
    "VALUES (%s, %s, %s, %s, %s) "
    "ON CONFLICT (event_id) DO NOTHING"
)

ALLOWED_RAW_TABLES: frozenset[str] = frozenset(
    {"raw.line_status", "raw.arrivals", "raw.disruptions"}
)

_RECONNECT_BACKOFF_SECONDS = 1.0

ConnectionFactory = Callable[[str], Awaitable[AsyncConnection]]


async def _default_connection_factory(dsn: str) -> AsyncConnection:
    return await psycopg.AsyncConnection.connect(dsn, autocommit=True)


class RawEventWriter:
    """Owns a single async psycopg connection; reconnects on transient errors.

    Inserts five-column envelopes into the configured ``raw.<topic>``
    table with ``ON CONFLICT (event_id) DO NOTHING`` for idempotency on
    replay. Any transient ``OperationalError`` is surfaced to the
    caller; production code wraps this in
    :class:`ingestion.consumers.RawEventConsumer` which catches and
    triggers a reconnect.
    """

    def __init__(
        self,
        dsn: str,
        *,
        table: str,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        if not dsn:
            raise ValueError("dsn must be a non-empty string")
        if table not in ALLOWED_RAW_TABLES:
            raise ValueError(f"table must be one of {sorted(ALLOWED_RAW_TABLES)}; got {table!r}")
        self._dsn = dsn
        self._table = table
        self._sql = INSERT_RAW_EVENT_SQL_TEMPLATE.format(table=table)
        self._connection_factory = connection_factory or _default_connection_factory
        self._conn: AsyncConnection | None = None

    @property
    def table(self) -> str:
        """The configured raw table name (``raw.<topic>``)."""
        return self._table

    @property
    def sql(self) -> str:
        """The interpolated INSERT statement bound to this writer's table."""
        return self._sql

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

    async def insert(self, event: Event[BaseModel]) -> int:
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
            table=self._table,
            event_id=str(event.event_id),
        ) as span:
            cursor = await conn.execute(self._sql, params)
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
                "ingestion.raw_event_writer.db_close_failed",
                table=self._table,
                error=repr(exc),
            )
        finally:
            self._conn = None

    def _require_connection(self) -> AsyncConnection:
        if self._conn is None:
            raise RuntimeError(
                "RawEventWriter is not active; use it as 'async with RawEventWriter(...)'"
            )
        return self._conn
