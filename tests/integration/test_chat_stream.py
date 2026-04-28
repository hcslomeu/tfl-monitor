"""Integration smoke test for ``POST /api/v1/chat/stream`` (TM-D5).

Hits the live agent stack: Anthropic Sonnet for synthesis, the
Pydantic AI Haiku normaliser, the Pinecone-backed RAG retriever, and
the Postgres-backed history sink. Marked ``integration`` and ``slow``
so the default hermetic suite stays free of API costs.

Run with::

    DATABASE_URL=... ANTHROPIC_API_KEY=... OPENAI_API_KEY=... \\
    PINECONE_API_KEY=... uv run pytest -m "integration and slow" \\
    tests/integration/test_chat_stream.py -v
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

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

THREAD = "tfl-monitor.integration.chat-stream"


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


def _parse_sse(text: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if not payload:
            continue
        frames.append(json.loads(payload))
    return frames


def test_chat_stream_emits_tokens_and_terminal_end(cleanup_thread: None) -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={"thread_id": THREAD, "message": "What is the Elizabeth line?"},
        )

    assert response.status_code == 200, response.text
    frames = _parse_sse(response.text)
    assert any(f["type"] == "token" for f in frames), "expected at least one token frame"
    assert frames, "stream produced no frames"
    assert frames[-1]["type"] == "end"
