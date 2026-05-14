"""Unit tests for ``api.agent.graph.compile_agent``."""

from __future__ import annotations

import pytest

from api.agent import graph as graph_module
from api.agent.graph import compile_agent

from .conftest import FakeChatModel

RETRIEVER_KEYS = ("OPENAI_API_KEY", "PINECONE_API_KEY")
LLM_KEYS = ("ANTHROPIC_API_KEY", "BEDROCK_REGION")


def _set_retriever_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in RETRIEVER_KEYS:
        monkeypatch.setenv(key, f"test-{key.lower()}")


def _clear_llm_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in LLM_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_compile_returns_none_when_openai_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_retriever_keys(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert compile_agent(pool=object(), model=FakeChatModel()) is None  # type: ignore[arg-type]


def test_compile_returns_none_when_pinecone_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_retriever_keys(monkeypatch)
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    assert compile_agent(pool=object(), model=FakeChatModel()) is None  # type: ignore[arg-type]


def test_compile_returns_none_when_no_llm_backend_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Bedrock region, no Anthropic key, no injected model → return None."""
    _set_retriever_keys(monkeypatch)
    _clear_llm_keys(monkeypatch)
    assert compile_agent(pool=object()) is None


def test_compile_smoke_invoke_with_fake_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retriever keys set + injected fake model → graph invokes deterministically.

    The fake model bypasses both backends, so no Bedrock or Anthropic
    credential needs to be present.
    """
    _set_retriever_keys(monkeypatch)
    _clear_llm_keys(monkeypatch)

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


def test_build_chat_model_picks_bedrock_when_region_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``BEDROCK_REGION`` set → ChatBedrockConverse selected."""
    monkeypatch.setenv("BEDROCK_REGION", "eu-west-2")
    monkeypatch.setenv(
        "BEDROCK_SONNET_MODEL_ID",
        "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-be-ignored")

    captured: dict[str, object] = {}

    class FakeBedrockConverse:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    import sys
    import types

    fake_module = types.ModuleType("langchain_aws")
    fake_module.ChatBedrockConverse = FakeBedrockConverse  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_aws", fake_module)

    model = graph_module._build_chat_model()
    assert isinstance(model, FakeBedrockConverse)
    assert captured["model"] == "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert captured["region_name"] == "eu-west-2"


def test_build_chat_model_falls_back_to_anthropic_when_region_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``BEDROCK_REGION`` unset + ``ANTHROPIC_API_KEY`` set → ChatAnthropic."""
    monkeypatch.delenv("BEDROCK_REGION", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")

    captured: dict[str, object] = {}

    def fake_chat_anthropic(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(graph_module, "ChatAnthropic", fake_chat_anthropic)

    model = graph_module._build_chat_model()
    assert model is not None
    assert captured["model_name"] == graph_module.DEFAULT_ANTHROPIC_MODEL


def test_build_chat_model_returns_none_when_no_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_llm_keys(monkeypatch)
    assert graph_module._build_chat_model() is None
