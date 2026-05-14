"""Compile the LangGraph chat agent.

Build the in-process ``create_react_agent`` over Sonnet, the five SQL +
RAG tools, and the rendered system prompt. The graph is compiled once
in the FastAPI lifespan and cached on ``app.state.agent``.

Two LLM backends are supported, selected by environment:

- **Bedrock** (production): set ``BEDROCK_REGION`` and
  ``BEDROCK_SONNET_MODEL_ID``. Uses
  ``langchain_aws.ChatBedrockConverse`` and the IAM credentials picked
  up by ``boto3`` from the standard chain (env vars on Lightsail).
- **Anthropic direct** (local dev fallback): leave ``BEDROCK_REGION``
  unset and provide ``ANTHROPIC_API_KEY``.

If any of ``OPENAI_API_KEY``, ``PINECONE_API_KEY`` is missing — or
neither LLM backend is configured — this module returns ``None`` so
the request handler can respond with an RFC 7807 ``503``.
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
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-latest"
DEFAULT_BEDROCK_SONNET_MODEL = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_MODEL_TIMEOUT_SECONDS = 60.0


def _build_chat_model() -> Any | None:
    """Return a configured chat model, or ``None`` if no backend is set.

    Bedrock takes precedence when ``BEDROCK_REGION`` is set. Anthropic
    direct is the fallback for local development.
    """
    bedrock_region = os.environ.get("BEDROCK_REGION")
    if bedrock_region:
        # Imported lazily so local dev environments without
        # langchain-aws installed can still run the Anthropic path.
        from langchain_aws import ChatBedrockConverse  # noqa: PLC0415

        model_id = os.environ.get("BEDROCK_SONNET_MODEL_ID", DEFAULT_BEDROCK_SONNET_MODEL)
        return ChatBedrockConverse(
            model=model_id,
            region_name=bedrock_region,
            temperature=0.0,
        )

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        return ChatAnthropic(
            model_name=DEFAULT_ANTHROPIC_MODEL,
            temperature=0.0,
            api_key=SecretStr(anthropic_key),
            timeout=DEFAULT_MODEL_TIMEOUT_SECONDS,
            stop=None,
        )

    return None


def compile_agent(
    *,
    pool: AsyncConnectionPool,
    model: Any | None = None,
) -> Any | None:
    """Build the agent or return ``None`` when required config is missing.

    Args:
        pool: Shared ``AsyncConnectionPool`` reused by every SQL tool.
        model: Optional pre-built chat model. Tests inject a fake here
            so they never hit a live LLM provider.

    Returns:
        Compiled LangGraph agent, or ``None`` when ``OPENAI_API_KEY``
        or ``PINECONE_API_KEY`` is unset, or when neither
        ``BEDROCK_REGION`` nor ``ANTHROPIC_API_KEY`` is set.
    """
    openai_key = os.environ.get("OPENAI_API_KEY")
    pinecone_key = os.environ.get("PINECONE_API_KEY")
    pinecone_index = os.environ.get("PINECONE_INDEX", DEFAULT_PINECONE_INDEX)

    if not (openai_key and pinecone_key):
        return None

    chat_model: Any = model if model is not None else _build_chat_model()
    if chat_model is None:
        return None

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
