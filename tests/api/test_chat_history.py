"""Unit tests for ``api.agent.history`` (TM-D5).

Exercises ``append_message`` and ``fetch_history`` directly against the
``FakeAsyncPool`` from ``tests/conftest.py``. The HTTP route is wired
by the orchestrator in a follow-up commit; route-level tests live in
``tests/api/test_chat_stream.py`` / future suites.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import ANY

import pytest

from api.agent.history import HISTORY_SQL, INSERT_SQL, append_message, fetch_history
from api.schemas import ChatMessageResponse


def _row(role: str, content: str, created_at: datetime) -> dict[str, Any]:
    return {"role": role, "content": content, "created_at": created_at}


@pytest.mark.asyncio
async def test_fetch_history_returns_rows_in_order(
    fake_pool_factory: Callable[..., Any],
) -> None:
    rows = [
        _row("user", "Hi", datetime(2026, 4, 28, 9, 0, tzinfo=UTC)),
        _row("assistant", "Hello back", datetime(2026, 4, 28, 9, 0, 1, tzinfo=UTC)),
    ]
    pool = fake_pool_factory(rows)

    result = await fetch_history(pool, thread_id="t-1")

    assert [r.role for r in result] == ["user", "assistant"]
    assert [r.content for r in result] == ["Hi", "Hello back"]
    assert all(isinstance(r, ChatMessageResponse) for r in result)
    sql, params = pool.conn.executed[0]
    assert sql == HISTORY_SQL
    assert params == {"thread_id": "t-1"}


@pytest.mark.asyncio
async def test_fetch_history_empty_returns_empty_list(
    fake_pool_factory: Callable[..., Any],
) -> None:
    pool = fake_pool_factory([])

    result = await fetch_history(pool, thread_id="never-seen")

    assert result == []
    sql, params = pool.conn.executed[0]
    assert sql == HISTORY_SQL
    assert params == {"thread_id": "never-seen"}


@pytest.mark.asyncio
async def test_append_message_then_fetch_round_trip(
    fake_pool_factory: Callable[..., Any],
) -> None:
    # Two empty batches for the two appends; one batch with the rows the
    # fetch is expected to return. Each cursor() call pops the next batch.
    rows = [
        _row("user", "ping", datetime(2026, 4, 28, 10, 0, tzinfo=UTC)),
        _row("assistant", "pong", datetime(2026, 4, 28, 10, 0, 1, tzinfo=UTC)),
    ]
    pool = fake_pool_factory([], [], rows)

    await append_message(pool, thread_id="t-2", role="user", content="ping")
    await append_message(pool, thread_id="t-2", role="assistant", content="pong")
    fetched = await fetch_history(pool, thread_id="t-2")

    assert [r.content for r in fetched] == ["ping", "pong"]
    assert pool.conn.executed == [
        (INSERT_SQL, {"thread_id": "t-2", "role": "user", "content": "ping"}),
        (INSERT_SQL, {"thread_id": "t-2", "role": "assistant", "content": "pong"}),
        (HISTORY_SQL, {"thread_id": "t-2"}),
    ]
    # Belt-and-braces: ANY guards against accidental positional drift.
    assert pool.conn.executed[2] == (HISTORY_SQL, ANY)
