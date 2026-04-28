"""Compile the LangGraph chat agent.

Build the in-process ``create_react_agent`` over Sonnet, the five SQL +
RAG tools, and the rendered system prompt. The graph is compiled once
in the FastAPI lifespan and cached on ``app.state.agent``.

If any of ``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ``PINECONE_API_KEY``
is missing, this module returns ``None`` so the request handler can
respond with an RFC 7807 ``503``.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent
from psycopg_pool import AsyncConnectionPool
from pydantic import SecretStr

from api.agent.prompts import render
from api.agent.rag import build_retriever
from api.agent.tools import make_tools

DEFAULT_PINECONE_INDEX = "tfl-strategy-docs"
DEFAULT_MODEL_NAME = "claude-3-5-sonnet-latest"
DEFAULT_MODEL_TIMEOUT_SECONDS = 60.0


def compile_agent(
    *,
    pool: AsyncConnectionPool,
    model: Any | None = None,
) -> Any | None:
    """Build the agent or return ``None`` if any required key is missing.

    Args:
        pool: Shared ``AsyncConnectionPool`` reused by every SQL tool.
        model: Optional pre-built chat model. Tests inject a fake here
            so they never hit the live Anthropic API.

    Returns:
        Compiled LangGraph agent, or ``None`` when one of
        ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` / ``PINECONE_API_KEY``
        is unset.
    """
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    pinecone_key = os.environ.get("PINECONE_API_KEY")
    pinecone_index = os.environ.get("PINECONE_INDEX", DEFAULT_PINECONE_INDEX)

    if not (anthropic_key and openai_key and pinecone_key):
        return None

    chat_model: Any = model
    if chat_model is None:
        # Bound timeout so a stalled Anthropic / network never hangs the
        # agent loop. 60 s matches the httpx default used in TM-B1.
        chat_model = ChatAnthropic(
            model_name=DEFAULT_MODEL_NAME,
            temperature=0.0,
            api_key=SecretStr(anthropic_key),
            timeout=DEFAULT_MODEL_TIMEOUT_SECONDS,
            stop=None,
        )

    retriever = build_retriever(
        pinecone_api_key=pinecone_key,
        openai_api_key=openai_key,
        index_name=pinecone_index,
    )
    tools = make_tools(pool=pool, retriever=retriever)
    return create_react_agent(
        model=chat_model,
        tools=tools,
        prompt=render(),
        checkpointer=InMemorySaver(),
    )
