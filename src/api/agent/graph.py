"""Compile the LangGraph chat agent.

Build the in-process ``create_react_agent`` over the four SQL tools (and
the pgvector RAG tool when reachable) and the rendered system prompt. The
graph is compiled once in the FastAPI lifespan and cached on
``app.state.agent``.

Two LLM backends are supported, selected by environment:

- **Bedrock** (production): set ``BEDROCK_REGION`` and
  ``BEDROCK_SONNET_MODEL_ID``. Uses
  ``langchain_aws.ChatBedrockConverse`` and the IAM credentials picked
  up by ``boto3`` from the standard chain (env vars on Lightsail).
- **Anthropic direct** (local dev fallback): leave ``BEDROCK_REGION``
  unset and provide ``ANTHROPIC_API_KEY``.

When neither LLM backend is configured this module returns ``None`` so
the request handler can respond with an RFC 7807 ``503``. The RAG tool is
optional: if the pgvector store cannot be reached the agent still serves
the SQL tools.
"""

from __future__ import annotations

import os
from typing import Any

import logfire
from psycopg_pool import AsyncConnectionPool
from pydantic import SecretStr

from api.agent.prompts import render

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
            timeout=int(DEFAULT_MODEL_TIMEOUT_SECONDS),
        )

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        from langchain_anthropic import ChatAnthropic  # noqa: PLC0415

        return ChatAnthropic(
            model_name=DEFAULT_ANTHROPIC_MODEL,
            temperature=0.0,
            api_key=SecretStr(anthropic_key),
            timeout=DEFAULT_MODEL_TIMEOUT_SECONDS,
            stop=None,
        )

    return None


def _build_retriever_or_none() -> Any | None:
    """Build the pgvector RAG retriever, or ``None`` when unavailable.

    Returns ``None`` (so the agent omits ``search_tfl_docs``) when no
    Postgres DSN is configured. Construction is lazy, so a populated
    table is not required at compile time — an empty/missing table just
    yields no snippets at query time.
    """
    try:
        from api.agent.rag import build_retriever  # noqa: PLC0415
        from rag.config import RagSettings  # noqa: PLC0415

        settings = RagSettings()
        _ = settings.vector_database_url  # raises when no DSN is configured
        return build_retriever(settings=settings)
    except Exception as exc:  # noqa: BLE001 - RAG is optional
        # Log the exception class only — the message can embed DSN fragments.
        logfire.info("agent_rag_retriever_unavailable", error_type=type(exc).__name__)
        return None


def compile_agent(
    *,
    pool: AsyncConnectionPool,
    model: Any | None = None,
) -> Any | None:
    """Build the agent or return ``None`` when no LLM backend is set.

    Args:
        pool: Shared ``AsyncConnectionPool`` reused by every SQL tool.
        model: Optional pre-built chat model. Tests inject a fake here
            so they never hit a live LLM provider.

    Returns:
        Compiled LangGraph agent, or ``None`` when neither
        ``BEDROCK_REGION`` nor ``ANTHROPIC_API_KEY`` is set.
    """
    chat_model: Any = model if model is not None else _build_chat_model()
    if chat_model is None:
        return None

    from langgraph.checkpoint.memory import InMemorySaver  # noqa: PLC0415
    from langgraph.prebuilt import create_react_agent  # noqa: PLC0415

    from api.agent.tools import make_tools  # noqa: PLC0415

    retriever = _build_retriever_or_none()
    tools = make_tools(pool=pool, retriever=retriever)
    return create_react_agent(
        model=chat_model,
        tools=tools,
        prompt=render(),
        checkpointer=InMemorySaver(),
    )
