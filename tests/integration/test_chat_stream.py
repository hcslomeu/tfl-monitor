"""Integration smoke test for ``POST /api/v1/chat/stream``.

Hits the live agent stack: Anthropic Claude for synthesis and the TfL
Unified API for tool calls. Marked ``integration`` and ``slow`` so the
default hermetic suite stays free of API costs.

Run with::

    ANTHROPIC_API_KEY=... TFL_APP_KEY=... \\
    uv run pytest -m "integration and slow" \\
    tests/integration/test_chat_stream.py -v
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(
        not (os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("TFL_APP_KEY")),
        reason="live agent stack requires ANTHROPIC_API_KEY and TFL_APP_KEY",
    ),
]

THREAD = "tfl-monitor.integration.chat-stream"


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


def test_chat_stream_emits_tokens_and_terminal_end() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={"thread_id": THREAD, "message": "Is the Victoria line running normally?"},
        )

    assert response.status_code == 200, response.text
    frames = _parse_sse(response.text)
    assert frames, "stream produced no frames"
    assert any(f["type"] == "token" for f in frames), "expected at least one token frame"
    assert frames[-1] == {"type": "end", "content": ""}
