"""CRUD helpers for ``analytics.chat_messages`` (TM-D5)."""

from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from api.schemas import ChatMessageResponse

INSERT_SQL = """
INSERT INTO analytics.chat_messages (thread_id, role, content)
VALUES (%(thread_id)s, %(role)s, %(content)s)
"""

HISTORY_SQL = """
SELECT role, content, created_at
FROM analytics.chat_messages
WHERE thread_id = %(thread_id)s
ORDER BY created_at ASC, id ASC
"""


async def append_message(
    pool: AsyncConnectionPool,
    *,
    thread_id: str,
    role: str,
    content: str,
) -> None:
    """Persist a single chat turn for ``thread_id``.

    Args:
        pool: Open ``AsyncConnectionPool`` (typically ``app.state.db_pool``).
        thread_id: Stable identifier for the conversation.
        role: One of ``user``, ``assistant``, ``system`` (enforced by
            the table's CHECK constraint).
        content: Raw turn text.
    """
    params: dict[str, Any] = {"thread_id": thread_id, "role": role, "content": content}
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(INSERT_SQL, params)


async def fetch_history(
    pool: AsyncConnectionPool,
    *,
    thread_id: str,
) -> list[ChatMessageResponse]:
    """Return every chat turn for ``thread_id`` in chronological order.

    Args:
        pool: Open ``AsyncConnectionPool``.
        thread_id: Conversation identifier.

    Returns:
        List of ``ChatMessageResponse`` ordered by ``created_at ASC, id ASC``.
        Empty list when the thread has no rows; callers map that to a
        404 problem (TM-D5 plan §2 decision #11).
    """
    params: dict[str, Any] = {"thread_id": thread_id}
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(HISTORY_SQL, params)
        rows: list[dict[str, Any]] = await cur.fetchall()
    return [ChatMessageResponse.model_validate(row) for row in rows]
