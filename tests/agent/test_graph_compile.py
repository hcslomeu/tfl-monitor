"""Unit tests for ``api.agent.graph.compile_agent``."""

from __future__ import annotations

import pytest

from api.agent import graph as graph_module
from api.agent.graph import _build_retriever_or_none, compile_agent

from .conftest import FakeChatModel

LLM_KEYS = ("ANTHROPIC_API_KEY", "BEDROCK_REGION")
DB_KEYS = ("RAG_DATABASE_URL", "DATABASE_URL")


def _clear_llm_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in LLM_KEYS:
        monkeypatch.delenv(key, raising=False)


def _clear_db_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in DB_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_compile_returns_none_when_no_llm_backend_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Bedrock region, no Anthropic key, no injected model → return None."""
    _clear_llm_keys(monkeypatch)
    assert compile_agent(pool=object()) is None


def test_compile_smoke_invoke_with_fake_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """An injected fake model + no DB → SQL-only agent that invokes deterministically.

    With no Postgres DSN configured the retriever is ``None``, so only the
    four SQL tools are bound. The fake model bypasses both LLM backends.
    """
    _clear_llm_keys(monkeypatch)
    _clear_db_keys(monkeypatch)

    fake_model = FakeChatModel(response="ack")
    agent = compile_agent(pool=object(), model=fake_model)  # type: ignore[arg-type]

    assert agent is not None
    out = agent.invoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"configurable": {"thread_id": "t-1"}},
    )
    assert out["messages"][-1].content == "ack"


def test_build_retriever_none_when_no_db_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """No DSN (vector_database_url raises) → retriever is omitted.

    Stubs RagSettings so a local .env DATABASE_URL cannot leak into the
    assertion (the settings class reads .env on construction).
    """

    class _NoDsnSettings:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        @property
        def vector_database_url(self) -> str:
            raise ValueError("no dsn configured")

    monkeypatch.setattr("rag.config.RagSettings", _NoDsnSettings)
    assert _build_retriever_or_none() is None


def test_build_retriever_built_when_db_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A DSN + a working build_retriever yields a retriever object."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:5432/db")
    sentinel = object()

    from api.agent import rag as rag_module

    monkeypatch.setattr(rag_module, "build_retriever", lambda **_kwargs: sentinel)
    assert _build_retriever_or_none() is sentinel


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

    import sys
    import types

    fake_module = types.ModuleType("langchain_anthropic")
    fake_module.ChatAnthropic = fake_chat_anthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_anthropic", fake_module)

    model = graph_module._build_chat_model()
    assert model is not None
    assert captured["model_name"] == graph_module.DEFAULT_ANTHROPIC_MODEL


def test_build_chat_model_returns_none_when_no_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_llm_keys(monkeypatch)
    assert graph_module._build_chat_model() is None
