"""Integration test for ``analytics.chat_messages`` round-trips (TM-D5).

Gated on the ``integration`` pytest marker so the default
``uv run task test`` run stays hermetic. Run explicitly with::

    DATABASE_URL=postgresql://tflmonitor:change_me@localhost:5432/tflmonitor \\
        uv run pytest -m integration tests/integration/test_chat_history.py -v

The test exercises ``append_message`` / ``fetch_history`` directly
against a live Postgres pool. The HTTP route ``GET /chat/{thread_id}/history``
is still 501 until the orchestrator wires the handler; route-level
integration coverage lives in a follow-up file.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest

psycopg = pytest.importorskip("psycopg")
psycopg_pool = pytest.importorskip("psycopg_pool")

DATABASE_URL = os.environ.get("DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="DATABASE_URL not set; skipping Postgres-dependent integration tests",
    ),
]


THREAD_ALPHA = "tfl-monitor.integration.chat-history.alpha"
THREAD_BETA = "tfl-monitor.integration.chat-history.beta"
THREAD_NEVER = "tfl-monitor.integration.chat-history.never-seen"


def _ensure_table(cur: object) -> None:
    """Create ``analytics.chat_messages`` if 004_chat.sql has not run yet."""
    assert hasattr(cur, "execute")
    cur.execute("CREATE SCHEMA IF NOT EXISTS analytics")  # type: ignore[attr-defined]
    cur.execute(  # type: ignore[attr-defined]
        """
        CREATE TABLE IF NOT EXISTS analytics.chat_messages (
            id          BIGSERIAL PRIMARY KEY,
            thread_id   TEXT NOT NULL,
            role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
            content     TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(  # type: ignore[attr-defined]
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_created "
        "ON analytics.chat_messages (thread_id, created_at)"
    )


@pytest.fixture
def cleanup_chat_messages() -> Iterator[None]:
    threads = (THREAD_ALPHA, THREAD_BETA, THREAD_NEVER)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            _ensure_table(cur)
            cur.execute(
                "DELETE FROM analytics.chat_messages WHERE thread_id = ANY(%s)",
                (list(threads),),
            )
        conn.commit()
    yield
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM analytics.chat_messages WHERE thread_id = ANY(%s)",
                (list(threads),),
            )
        conn.commit()


async def _run_round_trip() -> tuple[list[tuple[str, str]], list[object]]:
    from api.agent.history import append_message, fetch_history

    assert DATABASE_URL is not None
    pool = psycopg_pool.AsyncConnectionPool(DATABASE_URL, min_size=1, max_size=2, open=False)
    await pool.open()
    try:
        await append_message(pool, thread_id=THREAD_ALPHA, role="user", content="hi there")
        await append_message(pool, thread_id=THREAD_ALPHA, role="assistant", content="hello back")
        # Foreign thread row to confirm the WHERE clause isolates results.
        await append_message(pool, thread_id=THREAD_BETA, role="user", content="other thread")

        alpha = await fetch_history(pool, thread_id=THREAD_ALPHA)
        unseen = await fetch_history(pool, thread_id=THREAD_NEVER)
    finally:
        await pool.close()

    return [(m.role, m.content) for m in alpha], list(unseen)


def test_round_trip_orders_by_created_at_and_isolates_threads(
    cleanup_chat_messages: None,
) -> None:
    alpha_pairs, unseen = asyncio.run(_run_round_trip())

    assert alpha_pairs == [("user", "hi there"), ("assistant", "hello back")]
    assert unseen == []
