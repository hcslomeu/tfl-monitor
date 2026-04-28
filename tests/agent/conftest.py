"""Shared fixtures for the LangGraph agent unit tests.

Provides minimal fakes for the chat model and the LlamaIndex retriever
so the agent suite never touches the live Anthropic, OpenAI, or
Pinecone services.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
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


@dataclass
class FakeNode:
    """``NodeWithScore``-shaped object accepted by ``rag._to_snippet``."""

    metadata: dict[str, Any]
    text: str
    score: float


@dataclass
class FakeRetriever:
    """LlamaIndex ``BaseRetriever`` stand-in returning canned nodes."""

    nodes: list[FakeNode] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)

    async def aretrieve(self, query: str) -> list[FakeNode]:
        self.queries.append(query)
        return list(self.nodes)


def make_node(
    *,
    doc_id: str = "tfl_business_plan",
    doc_title: str = "TfL Business Plan",
    section_title: str = "Introduction",
    page_start: int | None = 1,
    page_end: int | None = 2,
    text: str = "snippet",
    score: float = 0.9,
    resolved_url: str = "https://example.com/doc.pdf",
) -> FakeNode:
    """Build a ``FakeNode`` with the metadata layout written by TM-D4."""
    return FakeNode(
        metadata={
            "doc_id": doc_id,
            "doc_title": doc_title,
            "section_title": section_title,
            "page_start": -1 if page_start is None else page_start,
            "page_end": -1 if page_end is None else page_end,
            "text": text,
            "resolved_url": resolved_url,
        },
        text=text,
        score=score,
    )


@pytest.fixture
def attach_agent() -> Iterator[Any]:
    """Attach a fake agent to ``app.state.agent`` and restore on teardown."""
    from api.main import app

    original = getattr(app.state, "agent", None)

    def _attach(agent: Any) -> None:
        app.state.agent = agent

    try:
        yield _attach
    finally:
        app.state.agent = original
