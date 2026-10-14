"""Shared fixtures for the LangGraph agent unit tests.

Provides a minimal fake chat model so the agent suite never touches the
live Anthropic API. ``attach_agent`` lives in
``tests/conftest.py`` so both the agent suite and the API suite (chat
stream tests) share it.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class FakeChatModel(BaseChatModel):
    """Deterministic ``BaseChatModel`` for graph compile/invoke tests.

    Emits a single ``AIMessage`` with ``response`` as the content. The
    ``bind_tools`` shim returns ``self`` so ``create_react_agent`` can
    bind without touching the Anthropic SDK.
    """

    response: str = "hello world"

    def _generate(
        self,
        messages: Any,
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        msg = AIMessage(content=self.response, tool_calls=[])
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    @property
    def _llm_type(self) -> str:
        return "fake-chat"
