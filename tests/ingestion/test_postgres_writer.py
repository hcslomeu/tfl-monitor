"""Unit tests for :class:`ingestion.consumers.RawEventWriter`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from contracts.schemas import LineStatusEvent, LineStatusPayload, TransportMode
from ingestion.consumers import RawEventWriter
from ingestion.consumers.postgres import (
    ALLOWED_RAW_TABLES,
    INSERT_RAW_EVENT_SQL_TEMPLATE,
)
from tests.ingestion.conftest import FakeAsyncConnection


def _build_event() -> LineStatusEvent:
    now = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)
    payload = LineStatusPayload(
        line_id="victoria",
        line_name="Victoria",
        mode=TransportMode.TUBE,
        status_severity=10,
        status_severity_description="Good Service",
        reason=None,
        valid_from=now,
        valid_to=now + timedelta(days=1),
    )
    return LineStatusEvent(
        event_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        event_type="line-status.snapshot",
        ingested_at=now,
        payload=payload,
    )


def _connection_factory(connections: list[FakeAsyncConnection]) -> Any:
    async def _factory(_: str) -> AsyncConnection:
        conn = connections.pop(0)
        return cast(AsyncConnection, conn)

    return _factory


async def test_insert_binds_envelope_columns_in_order() -> None:
    fake = FakeAsyncConnection(default_rowcount=1)
    event = _build_event()

    async with RawEventWriter(
        "postgresql://test",
        table="raw.line_status",
        connection_factory=_connection_factory([fake]),
    ) as writer:
        await writer.insert(event)

    assert len(fake.executed) == 1
    query, params = fake.executed[0]
    assert query == INSERT_RAW_EVENT_SQL_TEMPLATE.format(table="raw.line_status")
    assert params[0] == event.event_id
    assert params[1] == event.ingested_at
    assert params[2] == event.event_type
    assert params[3] == event.source
    assert isinstance(params[4], Jsonb)


async def test_insert_returns_rowcount() -> None:
    fake_inserted = FakeAsyncConnection(default_rowcount=1)
    fake_dup = FakeAsyncConnection(default_rowcount=0)
    event = _build_event()

    async with RawEventWriter(
        "postgresql://test",
        table="raw.line_status",
        connection_factory=_connection_factory([fake_inserted]),
    ) as writer:
        assert await writer.insert(event) == 1

    async with RawEventWriter(
        "postgresql://test",
        table="raw.line_status",
        connection_factory=_connection_factory([fake_dup]),
    ) as writer:
        assert await writer.insert(event) == 0


async def test_payload_is_serialised_via_jsonb() -> None:
    fake = FakeAsyncConnection(default_rowcount=1)
    event = _build_event()

    async with RawEventWriter(
        "postgresql://test",
        table="raw.line_status",
        connection_factory=_connection_factory([fake]),
    ) as writer:
        await writer.insert(event)

    _, params = fake.executed[0]
    jsonb = params[4]
    assert isinstance(jsonb, Jsonb)
    assert jsonb.obj == event.payload.model_dump(mode="json")


async def test_reconnect_closes_and_reopens() -> None:
    first = FakeAsyncConnection()
    second = FakeAsyncConnection()
    factory_calls = 0

    async def _factory(_: str) -> AsyncConnection:
        nonlocal factory_calls
        factory_calls += 1
        return cast(AsyncConnection, first if factory_calls == 1 else second)

    writer = RawEventWriter(
        "postgresql://test",
        table="raw.line_status",
        connection_factory=_factory,
    )
    async with writer:
        assert factory_calls == 1
        await writer.reconnect()
        assert factory_calls == 2
        assert first.closed is True


async def test_each_allowed_table_yields_distinct_sql() -> None:
    fake = FakeAsyncConnection()
    seen_queries: set[str] = set()

    for table in sorted(ALLOWED_RAW_TABLES):
        # Use a fresh fake per writer; we only inspect the bound SQL.
        local_fake = FakeAsyncConnection()
        writer = RawEventWriter(
            "postgresql://test",
            table=table,
            connection_factory=_connection_factory([local_fake]),
        )
        async with writer:
            assert writer.table == table
            assert writer.sql == INSERT_RAW_EVENT_SQL_TEMPLATE.format(table=table)
            seen_queries.add(writer.sql)

    # The table-name substitution must produce a distinct INSERT per table.
    assert len(seen_queries) == len(ALLOWED_RAW_TABLES)
    # Sanity: the placeholder fake never received a write.
    assert fake.executed == []


def test_constructor_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError):
        RawEventWriter("", table="raw.line_status")


def test_constructor_rejects_unknown_table() -> None:
    with pytest.raises(ValueError):
        RawEventWriter("postgresql://test", table="raw.evil_table")


def test_constructor_rejects_table_without_schema_prefix() -> None:
    with pytest.raises(ValueError):
        RawEventWriter("postgresql://test", table="line_status")
