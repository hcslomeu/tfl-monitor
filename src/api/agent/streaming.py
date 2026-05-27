"""Project LangGraph stream events to SSE frames.

Frames are dicts of ``{"type": "token"|"tool"|"end", "content": <str>}``.
``project`` maps a single ``(mode, payload)`` tuple from
``agent.astream(stream_mode=["messages","updates"])`` to zero or more
frames; ``serialise`` JSON-encodes a frame for the SSE ``data:`` line.
"""

from __future__ import annotations

import json
from typing import Any


def frame_token(text: str) -> dict[str, str] | None:
    """Wrap ``text`` in a ``token`` frame; ``None`` for empty strings."""
    if not text:
        return None
    return {"type": "token", "content": text}


def frame_tool(tool_name: str) -> dict[str, str]:
    """Wrap a tool invocation in a ``tool`` frame."""
    return {"type": "tool", "content": tool_name}


def frame_end(content: str = "") -> dict[str, str]:
    """Build the terminal ``end`` frame; ``content`` carries an error tag."""
    return {"type": "end", "content": content}


def frame_data(kind: str, payload: dict[str, Any]) -> dict[str, str]:
    """Wrap a structured tool result in a ``kind`` frame.

    ``content`` is the JSON-encoded ``payload`` so the SSE envelope stays
    uniform (``{"type": str, "content": str}``); the frontend decodes it
    into a typed view (``JourneyView`` / ``ArrivalsView``).
    """
    return {"type": kind, "content": json.dumps(payload, ensure_ascii=False)}


# Tool name -> structured frame kind. Only these tools return a dict the
# frontend renders as a card; every other tool result stays prose-only.
_CARD_TOOLS: dict[str, str] = {
    "plan_journey_tool": "journey",
    "get_arrivals_tool": "arrivals",
}


def project(mode: str, payload: Any) -> list[dict[str, str]]:
    """Map a single ``(mode, payload)`` chunk to zero or more SSE frames."""
    if mode == "messages":
        if not isinstance(payload, tuple) or len(payload) < 1:
            return []
        chunk = payload[0]
        # Only the assistant's own tokens become text frames. The
        # "messages" stream also replays ToolMessage chunks (the raw tool
        # result, e.g. the query_tube_status JSON) — those must never leak
        # into the chat bubble. The tool call itself is surfaced via the
        # "updates" tool frame instead.
        #
        # Streaming emits ``AIMessageChunk`` (``.type == "AIMessageChunk"``),
        # NOT the full ``AIMessage`` (``.type == "ai"``); a bare ``== "ai"``
        # check drops every streamed assistant token and the bubble renders
        # empty. Accept both; ``ToolMessage`` (``"tool"``) stays excluded.
        if getattr(chunk, "type", None) not in ("ai", "AIMessageChunk"):
            return []
        text = _extract_text(getattr(chunk, "content", None))
        f = frame_token(text)
        return [f] if f is not None else []
    if mode == "updates" and isinstance(payload, dict) and "tools" in payload:
        tools_payload = payload["tools"]
        if isinstance(tools_payload, dict):
            tool_messages = tools_payload.get("messages", [])
            frames: list[dict[str, str]] = []
            for m in tool_messages:
                name = getattr(m, "name", "tool")
                frames.append(frame_tool(name))
                card = _card_frame(name, getattr(m, "content", None))
                if card is not None:
                    frames.append(card)
            return frames
    return []


def _card_frame(tool_name: str, content: Any) -> dict[str, str] | None:
    """Build a structured card frame for a known tool, else ``None``.

    A card tool returns a dict on success (LangChain JSON-encodes it into
    ``ToolMessage.content``) or a plain error string when it cannot answer.
    Only the JSON-object case yields a frame; anything else stays prose.
    """
    kind = _CARD_TOOLS.get(tool_name)
    if kind is None or not isinstance(content, str):
        return None
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return frame_data(kind, payload)


def _extract_text(content: Any) -> str:
    """Pull the human-readable text out of a LangChain message ``content``.

    Handles three shapes emitted by LangChain + Anthropic:

    - ``None`` → empty string.
    - ``str`` → returned as-is.
    - ``list`` of Anthropic content blocks → concatenated ``text``
      blocks. Tool-use blocks (no ``text`` key) are dropped.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_part = block.get("text", "")
                if isinstance(text_part, str):
                    parts.append(text_part)
        return "".join(parts)
    return ""


def serialise(frame: dict[str, str]) -> str:
    """JSON-encode an SSE frame for the ``data:`` line."""
    return json.dumps(frame, ensure_ascii=False)
