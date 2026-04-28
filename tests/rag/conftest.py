"""Shared fixtures for ``tests/rag/``."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _rag_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``RagSettings()`` constructs in unit tests."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
    monkeypatch.setenv("PINECONE_API_KEY", "pcsk-test-pinecone")
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
