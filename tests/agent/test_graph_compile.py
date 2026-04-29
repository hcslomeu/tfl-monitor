"""Unit tests for ``api.agent.graph.compile_agent``."""

from __future__ import annotations

import pytest

from api.agent import graph as graph_module
from api.agent.graph import compile_agent

from .conftest import FakeChatModel

REQUIRED_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PINECONE_API_KEY")


def _set_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in REQUIRED_KEYS:
        monkeypatch.setenv(key, f"test-{key.lower()}")


def test_compile_returns_none_when_anthropic_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_keys(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert compile_agent(pool=object(), model=FakeChatModel()) is None  # type: ignore[arg-type]


def test_compile_returns_none_when_openai_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_keys(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert compile_agent(pool=object(), model=FakeChatModel()) is None  # type: ignore[arg-type]


def test_compile_returns_none_when_pinecone_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_keys(monkeypatch)
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    assert compile_agent(pool=object(), model=FakeChatModel()) is None  # type: ignore[arg-type]


def test_compile_smoke_invoke_with_fake_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """All keys set + injected fake model → graph invokes deterministically."""
    _set_keys(monkeypatch)

    def fake_build_retriever(**_kwargs: object) -> dict[str, object]:
        return {}

    monkeypatch.setattr(graph_module, "build_retriever", fake_build_retriever)

    fake_model = FakeChatModel(response="ack")
    agent = compile_agent(pool=object(), model=fake_model)  # type: ignore[arg-type]

    assert agent is not None

    out = agent.invoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"configurable": {"thread_id": "t-1"}},
    )
    last_message = out["messages"][-1]
    assert last_message.content == "ack"
