"""Integration: stream a turn then read it back via ``/history`` (TM-D5).

Confirms that the SSE handler persists both the user input and the
assistant response, and that ``GET /chat/{thread_id}/history`` surfaces
both rows in chronological order.

Same gates and cost profile as ``tests/integration/test_chat_stream.py``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

psycopg = pytest.importorskip("psycopg")

DATABASE_URL = os.environ.get("DATABASE_URL")
REQUIRED_KEYS = ("DATABASE_URL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PINECONE_API_KEY")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(
        any(not os.environ.get(k) for k in REQUIRED_KEYS),
        reason=(
            "full agent stack requires DATABASE_URL plus Anthropic, OpenAI, and Pinecone API keys"
        ),
    ),
]

THREAD = "tfl-monitor.integration.chat-history-after-stream"


@pytest.fixture
def cleanup_thread() -> Iterator[None]:
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS analytics")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS analytics.chat_messages (
                    id BIGSERIAL PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL
                        CHECK (role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                "DELETE FROM analytics.chat_messages WHERE thread_id = %s",
                (THREAD,),
            )
        conn.commit()
    yield
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM analytics.chat_messages WHERE thread_id = %s",
                (THREAD,),
            )
        conn.commit()


def test_history_reflects_streamed_turn(cleanup_thread: None) -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as client:
        stream_response = client.post(
            "/api/v1/chat/stream",
            json={"thread_id": THREAD, "message": "Hello agent"},
        )
        assert stream_response.status_code == 200, stream_response.text

        history_response = client.get(f"/api/v1/chat/{THREAD}/history")

    assert history_response.status_code == 200, history_response.text
    rows = history_response.json()
    assert len(rows) == 2
    assert rows[0]["role"] == "user"
    assert rows[0]["content"] == "Hello agent"
    assert rows[1]["role"] == "assistant"
    assert rows[1]["content"]  # non-empty response synthesised by the agent
