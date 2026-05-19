"""Regression: importing ``api.main`` must not eagerly load heavy deps.

Cold-start on the Lightsail box is dominated by the transitive import
graph of ``langchain_anthropic`` (pulls ``transformers`` + ``torch`` +
``cv2``), ``llama_index``, ``pydantic_ai``, and ``docling``. Those
imports must be deferred until the first chat request actually needs
them so ``/health`` and the SQL endpoints stay responsive.

This test re-imports ``api.main`` in a clean subprocess and asserts the
forbidden modules are absent from ``sys.modules`` after the import.
"""

from __future__ import annotations

import os
import subprocess
import sys

FORBIDDEN = (
    "docling",
    "torch",
    "transformers",
    "llama_index",
    "langchain_anthropic",
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
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    loaded = result.stdout.strip()
    assert loaded == "[]", (
        f"Heavy modules unexpectedly loaded by `from api.main import app`: {loaded}. "
        "Move the offending import inside the function/endpoint that needs it."
    )
