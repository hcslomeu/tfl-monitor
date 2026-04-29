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


def project(mode: str, payload: Any) -> list[dict[str, str]]:
    """Map a single ``(mode, payload)`` chunk to zero or more SSE frames."""
    if mode == "messages":
        if not isinstance(payload, tuple) or len(payload) < 1:
            return []
        chunk = payload[0]
        text = _extract_text(getattr(chunk, "content", None))
        f = frame_token(text)
        return [f] if f is not None else []
    if mode == "updates" and isinstance(payload, dict) and "tools" in payload:
        tools_payload = payload["tools"]
        if isinstance(tools_payload, dict):
            tool_messages = tools_payload.get("messages", [])
            return [frame_tool(getattr(m, "name", "tool")) for m in tool_messages]
    return []


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
