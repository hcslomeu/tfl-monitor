"""Unit tests for ``api.agent.graph.compile_agent``."""

from __future__ import annotations

import sys
import types

import pytest

from api.agent import graph as graph_module
from api.agent.graph import compile_agent

from .conftest import FakeChatModel


def _fake_chat_anthropic(monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]) -> None:
    """Swap ``langchain_anthropic.ChatAnthropic`` for a kwargs recorder."""

    def fake_chat_anthropic(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    fake_module = types.ModuleType("langchain_anthropic")
    fake_module.ChatAnthropic = fake_chat_anthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_anthropic", fake_module)


def test_compile_returns_none_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Anthropic key and no injected model → return None."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert compile_agent() is None


def test_compile_smoke_invoke_with_fake_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """An injected fake model and no TfL client → tool-less agent that invokes."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    agent = compile_agent(model=FakeChatModel(response="ack"))

    assert agent is not None
    out = agent.invoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"configurable": {"thread_id": "t-1"}},
    )
    assert out["messages"][-1].content == "ack"


def test_build_chat_model_defaults_to_haiku(monkeypatch: pytest.MonkeyPatch) -> None:
    """Key set, ``CHAT_MODEL`` unset → default model, low effort, no sampling params."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    captured: dict[str, object] = {}
    _fake_chat_anthropic(monkeypatch, captured)

    assert graph_module._build_chat_model() is not None
    assert captured["model_name"] == graph_module.DEFAULT_CHAT_MODEL
    assert captured["max_tokens_to_sample"] == graph_module.MAX_RESPONSE_TOKENS
    assert captured["effort"] == "low"
    # Current Claude models reject non-default sampling parameters.
    assert "temperature" not in captured


def test_build_chat_model_honours_chat_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("CHAT_MODEL", "claude-sonnet-5-5")
    captured: dict[str, object] = {}
    _fake_chat_anthropic(monkeypatch, captured)

    graph_module._build_chat_model()

    assert captured["model_name"] == "claude-sonnet-5-5"


def test_build_chat_model_returns_none_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert graph_module._build_chat_model() is None
