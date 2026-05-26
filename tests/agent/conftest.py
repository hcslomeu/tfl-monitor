"""Shared fixtures for the LangGraph agent unit tests.

Provides minimal fakes for the chat model and the pgvector-backed
LlamaIndex retriever so the agent suite never touches live Anthropic,
Bedrock, or Postgres services. ``attach_agent`` lives in
``tests/conftest.py`` so both the agent suite and the API suite (chat
stream tests) share it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass
class FakeIndex:
    """``VectorStoreIndex`` stand-in for ``api.agent.rag.retrieve``.

    ``as_retriever`` records the ``similarity_top_k`` and ``filters``
    arguments and returns a :class:`FakeRetriever` scoped to the
    ``doc_id`` metadata filter (mirroring pgvector's WHERE clause). Set
    ``raise_on_retriever`` to exercise the graceful-degradation path.
    """

    nodes: list[FakeNode] = field(default_factory=list)
    captured: dict[str, Any] = field(default_factory=dict)
    last_retriever: FakeRetriever | None = None
    raise_on_retriever: bool = False

    def as_retriever(self, *, similarity_top_k: int, filters: Any = None) -> FakeRetriever:
        if self.raise_on_retriever:
            raise RuntimeError("pgvector unreachable")
        self.captured = {"top_k": similarity_top_k, "filters": filters}
        nodes = self.nodes
        if filters is not None:
            wanted = filters.filters[0].value
            nodes = [n for n in self.nodes if n.metadata.get("doc_id") == wanted]
        self.last_retriever = FakeRetriever(nodes=nodes)
        return self.last_retriever


def make_node(
    *,
    doc_id: str = "business_plan_2026",
    doc_title: str = "TfL Business Plan 2026",
    section_title: str = "Introduction",
    page_start: int | None = 1,
    page_end: int | None = 2,
    text: str = "snippet",
    score: float = 0.9,
    resolved_url: str = "https://example.com/doc.pdf",
) -> FakeNode:
    """Build a ``FakeNode`` with the metadata layout written at upsert."""
    return FakeNode(
        # Real pgvector nodes carry text on the node, not in metadata; the
        # snippet adapter falls back to node.text, so don't duplicate it here.
        metadata={
            "doc_id": doc_id,
            "doc_title": doc_title,
            "section_title": section_title,
            "page_start": -1 if page_start is None else page_start,
            "page_end": -1 if page_end is None else page_end,
            "resolved_url": resolved_url,
        },
        text=text,
        score=score,
    )
