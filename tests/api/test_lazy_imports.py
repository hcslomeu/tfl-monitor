"""Regression: importing ``api.main`` must not eagerly load heavy deps.

Cold-start on the Lightsail box is dominated by the transitive import
graph of ``langchain_anthropic``, ``llama_index``, and ``pydantic_ai``.
Those imports must be deferred until the first chat request actually
needs them so ``/health`` and the SQL endpoints stay responsive. The
heavyweight transitive deps that earlier RAG stacks pulled (``torch``,
``transformers``, ``cv2``, ``pinecone``) must never re-enter the eager
import graph either.

This test re-imports ``api.main`` in a clean subprocess and asserts the
forbidden modules are absent from ``sys.modules`` after the import.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

FORBIDDEN = (
    "torch",
    "transformers",
    "llama_index",
    "langchain_anthropic",
    "langchain_core",
    "langgraph",
    "pinecone",
    "pydantic_ai",
    "cv2",
)


def test_api_main_does_not_eagerly_load_heavy_modules() -> None:
    """``from api.main import app`` must keep heavy modules out of sys.modules."""
    script = (
        "import sys, json\n"
        "from api.main import app  # noqa: F401\n"
        f"forbidden = {FORBIDDEN!r}\n"
        "loaded = sorted(m for m in forbidden if m in sys.modules)\n"
        "print(json.dumps(loaded))\n"
    )
    # Strip pytest/coverage env so the subprocess starts with a pristine
    # interpreter; coverage's ``.pth`` hook would otherwise preload
    # tracing infrastructure that pulls some of the very modules we are
    # asserting absent.
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("COV_CORE", "COVERAGE_", "PYTEST_"))
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        # Surface stderr + stdout so a failing subprocess gives an
        # actionable trace instead of "exited with code 1".
        pytest.fail(
            f"subprocess exited with code {result.returncode}:\n"
            f"stderr:\n{result.stderr}\n"
            f"stdout:\n{result.stdout}"
        )
    # ``api.main`` may emit logfire / deprecation lines on stdout; take
    # the last non-empty line as the JSON payload so unrelated chatter
    # does not turn this assertion into a misleading mismatch.
    stdout_lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert stdout_lines, f"subprocess produced no stdout:\n{result.stderr}"
    loaded = json.loads(stdout_lines[-1])
    assert loaded == [], (
        f"Heavy modules unexpectedly loaded by `from api.main import app`: {loaded}. "
        "Move the offending import inside the function/endpoint that needs it."
    )
