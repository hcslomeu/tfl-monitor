"""Unit tests for ``POST /api/v1/chat/stream`` (TM-D5).

Wires a ``FakeAgent`` into ``app.state.agent`` to exercise the SSE
projection without ever talking to the LLM.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
from fastapi.testclient import TestClient

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
    """Build a ``messages``-mode payload yielding a token frame.

    ``type="AIMessageChunk"`` mirrors what LangGraph's ``messages`` stream
    actually emits for assistant tokens (the streamed chunk type, NOT the
    full ``AIMessage`` whose type is ``"ai"``). Only assistant chunks
    become token frames; tool-result chunks are skipped.
    """
    return ("messages", (SimpleNamespace(content=text, type="AIMessageChunk"), {}))


def _tool_message_chunk(content: str) -> tuple[str, tuple[Any, dict[str, Any]]]:
    """Build a ``messages``-mode ToolMessage chunk (raw tool result)."""
    return ("messages", (SimpleNamespace(content=content, type="tool"), {}))


def _tool_event(tool_name: str) -> tuple[str, dict[str, Any]]:
    """Build an ``updates``-mode payload yielding a tool frame."""
    return (
        "updates",
        {"tools": {"messages": [SimpleNamespace(name=tool_name)]}},
    )


def _tool_event_with_content(tool_name: str, content: str) -> tuple[str, dict[str, Any]]:
    """Build an ``updates``-mode tool event carrying a result ``content``.

    Mirrors what LangGraph emits after a tool node runs: the ``ToolMessage``
    exposes both ``name`` and the (JSON-encoded) ``content`` of the return.
    """
    return (
        "updates",
        {"tools": {"messages": [SimpleNamespace(name=tool_name, content=content)]}},
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


def test_chat_stream_happy_path_streams(
    attach_agent: Callable[[Any], None],
) -> None:
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

    assert len(agent.calls) == 1
    assert agent.calls[0]["config"] == {
        "configurable": {"thread_id": "t-happy"},
        "recursion_limit": 12,
    }
    assert agent.calls[0]["stream_mode"] == ["messages", "updates"]


def test_chat_stream_emits_tool_frame(
    attach_agent: Callable[[Any], None],
) -> None:
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


def test_chat_stream_skips_tool_message_content(
    attach_agent: Callable[[Any], None],
) -> None:
    """ToolMessage chunks (raw tool-result JSON) must not leak as tokens."""
    agent = FakeAgent(
        frames=[
            _tool_message_chunk('[{"line_id": "piccadilly", "status": "Severe Delays"}]'),
            _token_chunk("Piccadilly has severe delays."),
        ]
    )
    attach_agent(agent)

    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t-toolmsg", "message": "delays?"},
    )

    assert response.status_code == 200
    frames = _parse_sse(response.text)
    # The tool-result JSON is absent; only the assistant token + end remain.
    assert frames == [
        {"type": "token", "content": "Piccadilly has severe delays."},
        {"type": "end", "content": ""},
    ]


def test_chat_stream_emits_journey_card_frame(
    attach_agent: Callable[[Any], None],
) -> None:
    """A successful plan_journey_tool result yields a `journey` card frame."""
    view = {
        "total_minutes": 38,
        "start": "2026-05-27T14:02:00",
        "arrival": "2026-05-27T14:40:00",
        "legs": [{"mode": "tube", "summary": "Metropolitan to Uxbridge", "minutes": 38}],
    }
    agent = FakeAgent(
        frames=[
            _tool_event_with_content("plan_journey_tool", json.dumps(view)),
            _token_chunk("Here is your route."),
        ]
    )
    attach_agent(agent)

    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t-journey", "message": "Baker Street to Uxbridge"},
    )

    assert response.status_code == 200
    frames = _parse_sse(response.text)
    assert frames == [
        {"type": "tool", "content": "plan_journey_tool"},
        {"type": "journey", "content": json.dumps(view)},
        {"type": "token", "content": "Here is your route."},
        {"type": "end", "content": ""},
    ]


def test_chat_stream_emits_arrivals_card_frame(
    attach_agent: Callable[[Any], None],
) -> None:
    """A successful get_arrivals_tool result yields an `arrivals` card frame."""
    view = {
        "station": "Bank",
        "platforms": [
            {
                "platform": "Northbound - Platform 2",
                "arrivals": [{"line": "Northern", "destination": "Morden", "seconds": 90}],
            }
        ],
    }
    agent = FakeAgent(frames=[_tool_event_with_content("get_arrivals_tool", json.dumps(view))])
    attach_agent(agent)

    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t-arrivals", "message": "next arrivals at Bank"},
    )

    assert response.status_code == 200
    frames = _parse_sse(response.text)
    assert frames == [
        {"type": "tool", "content": "get_arrivals_tool"},
        {"type": "arrivals", "content": json.dumps(view)},
        {"type": "end", "content": ""},
    ]


def test_chat_stream_card_tool_error_string_has_no_card_frame(
    attach_agent: Callable[[Any], None],
) -> None:
    """When a card tool returns a plain error string, no card frame is emitted."""
    agent = FakeAgent(
        frames=[
            _tool_event_with_content("plan_journey_tool", "Couldn't find station 'Atlantis'."),
            _token_chunk("I couldn't find that station."),
        ]
    )
    attach_agent(agent)

    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t-journey-err", "message": "Atlantis to Bank"},
    )

    assert response.status_code == 200
    frames = _parse_sse(response.text)
    assert frames == [
        {"type": "tool", "content": "plan_journey_tool"},
        {"type": "token", "content": "I couldn't find that station."},
        {"type": "end", "content": ""},
    ]


def test_chat_stream_503_when_agent_missing(
    attach_agent: Callable[[Any], None],
) -> None:
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
    """Agent that raises ``error`` mid-stream after emitting one token."""

    error: Exception
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
            raise self.error

        return _gen()


def test_chat_stream_error_ends_with_error_frame(
    attach_agent: Callable[[Any], None],
) -> None:
    attach_agent(FailingAgent(error=RuntimeError("upstream model crashed")))

    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t-error", "message": "trigger crash"},
    )

    assert response.status_code == 200
    frames = _parse_sse(response.text)
    assert frames == [
        {"type": "token", "content": "partial "},
        {"type": "end", "content": "error"},
    ]


def test_chat_stream_llm_rejection_explains_itself(
    attach_agent: Callable[[Any], None],
) -> None:
    """An Anthropic API rejection (e.g. workspace spend limit) yields a readable token."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    rejection = anthropic.BadRequestError(
        "workspace usage limit reached",
        response=httpx.Response(400, request=request),
        body=None,
    )
    attach_agent(FailingAgent(error=rejection))

    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t-limit", "message": "status?"},
    )

    assert response.status_code == 200
    frames = _parse_sse(response.text)
    assert frames[-1] == {"type": "end", "content": "error"}
    assert frames[-2]["type"] == "token"
    assert "unavailable" in frames[-2]["content"]
