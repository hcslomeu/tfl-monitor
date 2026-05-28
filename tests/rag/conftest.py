"""Shared fixtures for ``tests/rag/``."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _rag_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``RagSettings()`` constructs in unit tests."""
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
