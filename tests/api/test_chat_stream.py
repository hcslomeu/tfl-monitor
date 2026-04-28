"""Unit tests for ``POST /api/v1/chat/stream`` (TM-D5).

Wires a ``FakeAgent`` into ``app.state.agent`` and a ``FakeAsyncPool``
into ``app.state.db_pool`` to exercise the SSE projection plus the
chat-history side effect without ever talking to Anthropic, OpenAI,
Pinecone, or Postgres.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from api.agent.history import INSERT_SQL
from api.main import app


@dataclass
class FakeAgent:
    """Stand-in for a compiled LangGraph agent.

    ``astream`` yields the canned ``(mode, payload)`` tuples in
    ``frames`` and records every invocation so tests can assert the
    request-side wiring (thread_id, message) is correct.
    """

    frames: list[tuple[str, Any]]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def astream(
        self,
        inputs: Any,
        *,
        config: Any,
        stream_mode: Any,
    ) -> AsyncIterator[tuple[str, Any]]:
        self.calls.append({"inputs": inputs, "config": config, "stream_mode": stream_mode})

        async def _gen() -> AsyncIterator[tuple[str, Any]]:
            for frame in self.frames:
                yield frame

        return _gen()


def _token_chunk(text: str) -> tuple[str, tuple[Any, dict[str, Any]]]:
    """Build a ``messages``-mode payload yielding a token frame."""
    return ("messages", (SimpleNamespace(content=text), {}))


def _tool_event(tool_name: str) -> tuple[str, dict[str, Any]]:
    """Build an ``updates``-mode payload yielding a tool frame."""
    return (
        "updates",
        {"tools": {"messages": [SimpleNamespace(name=tool_name)]}},
    )


def _parse_sse(text: str) -> list[dict[str, str]]:
    """Extract JSON-decoded ``data:`` payloads from a buffered SSE response."""
    frames: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if not payload:
            continue
        frames.append(json.loads(payload))
    return frames


def test_chat_stream_happy_path_persists_and_streams(
    fake_pool_factory: Callable[..., Any],
    attach_pool: Callable[[Any], None],
    attach_agent: Callable[[Any], None],
) -> None:
    pool = fake_pool_factory([], [])  # one batch per INSERT
    attach_pool(pool)
    agent = FakeAgent(
        frames=[
            _token_chunk("He"),
            _token_chunk("llo"),
        ]
    )
    attach_agent(agent)

    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t-happy", "message": "hi there"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    frames = _parse_sse(response.text)
    assert frames == [
        {"type": "token", "content": "He"},
        {"type": "token", "content": "llo"},
        {"type": "end", "content": ""},
    ]

    assert pool.conn.executed == [
        (INSERT_SQL, {"thread_id": "t-happy", "role": "user", "content": "hi there"}),
        (INSERT_SQL, {"thread_id": "t-happy", "role": "assistant", "content": "Hello"}),
    ]
    assert len(agent.calls) == 1
    assert agent.calls[0]["config"] == {"configurable": {"thread_id": "t-happy"}}
    assert agent.calls[0]["stream_mode"] == ["messages", "updates"]


def test_chat_stream_emits_tool_frame(
    fake_pool_factory: Callable[..., Any],
    attach_pool: Callable[[Any], None],
    attach_agent: Callable[[Any], None],
) -> None:
    pool = fake_pool_factory([], [])
    attach_pool(pool)
    agent = FakeAgent(
        frames=[
            _token_chunk("Looking up "),
            _tool_event("query_tube_status"),
            _token_chunk("the data..."),
        ]
    )
    attach_agent(agent)

    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t-tool", "message": "status?"},
    )

    assert response.status_code == 200
    frames = _parse_sse(response.text)
    assert frames == [
        {"type": "token", "content": "Looking up "},
        {"type": "tool", "content": "query_tube_status"},
        {"type": "token", "content": "the data..."},
        {"type": "end", "content": ""},
    ]
    # Only token content lands in the persisted assistant turn.
    assistant_insert = pool.conn.executed[1]
    assert assistant_insert[1]["content"] == "Looking up the data..."


def test_chat_stream_503_when_agent_missing(
    fake_pool_factory: Callable[..., Any],
    attach_pool: Callable[[Any], None],
    attach_agent: Callable[[Any], None],
) -> None:
    attach_pool(fake_pool_factory())
    attach_agent(None)

    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t-no-agent", "message": "hi"},
    )

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["title"] == "Service Unavailable"
    assert body["detail"] == "Chat agent is not configured"


def test_chat_stream_503_when_pool_missing(
    attach_pool: Callable[[Any], None],
    attach_agent: Callable[[Any], None],
) -> None:
    attach_pool(None)
    attach_agent(FakeAgent(frames=[]))

    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t-no-pool", "message": "hi"},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["detail"] == "Database pool is not available"


def test_chat_stream_422_on_empty_message() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t-bad", "message": ""},
    )
    assert response.status_code == 422


def test_chat_stream_422_on_oversized_message() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t-bad", "message": "x" * 4001},
    )
    assert response.status_code == 422


@dataclass
class FailingAgent:
    """Agent that raises mid-stream after emitting one token.

    Exercises the ``finally`` block's ``completed`` guard so a truncated
    assistant turn never lands in ``analytics.chat_messages``.
    """

    calls: list[dict[str, Any]] = field(default_factory=list)

    def astream(
        self,
        inputs: Any,
        *,
        config: Any,
        stream_mode: Any,
    ) -> AsyncIterator[tuple[str, Any]]:
        self.calls.append({"inputs": inputs, "config": config, "stream_mode": stream_mode})

        async def _gen() -> AsyncIterator[tuple[str, Any]]:
            yield _token_chunk("partial ")
            raise RuntimeError("upstream model crashed")

        return _gen()


def test_chat_stream_error_does_not_persist_partial_assistant(
    fake_pool_factory: Callable[..., Any],
    attach_pool: Callable[[Any], None],
    attach_agent: Callable[[Any], None],
) -> None:
    pool = fake_pool_factory([])  # only the user INSERT should fire
    attach_pool(pool)
    attach_agent(FailingAgent())

    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t-error", "message": "trigger crash"},
    )

    assert response.status_code == 200
    frames = _parse_sse(response.text)
    assert frames[-1] == {"type": "end", "content": "error"}
    # Exactly one INSERT — the user turn before streaming. The truncated
    # assistant text must NOT have been persisted.
    assert pool.conn.executed == [
        (INSERT_SQL, {"thread_id": "t-error", "role": "user", "content": "trigger crash"}),
    ]
