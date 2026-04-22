"""Placeholder LangGraph graph.

The real routing agent (SQL tool + RAG tool + Pydantic AI extraction)
lands in TM-D5. This scaffold only proves that the graph compiles and that
LangSmith tracing is acknowledged at import time.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from agent.observability import validate_langsmith_env


class AgentState(TypedDict):
    messages: list[dict[str, str]]


def noop(state: AgentState) -> AgentState:
    """Echo the incoming messages plus a ``not-implemented`` assistant turn."""
    return {
        "messages": [*state["messages"], {"role": "assistant", "content": "not-implemented"}],
    }


validate_langsmith_env()

_graph: StateGraph[AgentState] = StateGraph(AgentState)
_graph.add_node("noop", noop)
_graph.set_entry_point("noop")
_graph.add_edge("noop", END)
app = _graph.compile()
