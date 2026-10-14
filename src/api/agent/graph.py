"""Compile the LangGraph chat agent.

Build the in-process ``create_react_agent`` over the live TfL tools and
the rendered system prompt. The graph is compiled once in the FastAPI
lifespan and cached on ``app.state.agent``.

The LLM is Anthropic Claude via the direct API (ADR 015). The model id
comes from ``CHAT_MODEL`` so it can change without a deploy; spend is
capped by the Anthropic workspace that issued ``ANTHROPIC_API_KEY``.
When no key is set this module returns ``None`` so the request handler
can respond with an RFC 7807 ``503``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr

from api.agent.prompts import render

if TYPE_CHECKING:
    from ingestion.tfl_client.client import TflClient

DEFAULT_CHAT_MODEL = "claude-haiku-5-5"
DEFAULT_MODEL_TIMEOUT_SECONDS = 60.0
# Hard ceiling on one model response, thinking included. Answers are
# short by prompt design; the cap bounds the cost of a runaway turn.
MAX_RESPONSE_TOKENS = 4096


def _build_chat_model() -> Any | None:
    """Return the configured chat model, or ``None`` without an API key."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    from langchain_anthropic import ChatAnthropic  # noqa: PLC0415

    return ChatAnthropic(
        model_name=os.environ.get("CHAT_MODEL") or DEFAULT_CHAT_MODEL,
        api_key=SecretStr(api_key),
        max_tokens_to_sample=MAX_RESPONSE_TOKENS,
        effort="low",
        timeout=DEFAULT_MODEL_TIMEOUT_SECONDS,
        stop=None,
        # Top-level automatic prompt caching: the system prompt and tool
        # schemas are identical on every request.
        model_kwargs={"cache_control": {"type": "ephemeral"}},
    )


def compile_agent(
    *,
    tfl_client: TflClient | None = None,
    model: Any | None = None,
) -> Any | None:
    """Build the agent or return ``None`` when no LLM backend is set.

    Args:
        tfl_client: Optional ``TflClient`` powering the live tools. When
            ``None`` the agent runs without tools.
        model: Optional pre-built chat model. Tests inject a fake here
            so they never hit a live LLM provider.

    Returns:
        Compiled LangGraph agent, or ``None`` when ``ANTHROPIC_API_KEY``
        is not set.
    """
    chat_model: Any = model if model is not None else _build_chat_model()
    if chat_model is None:
        return None

    from langgraph.checkpoint.memory import InMemorySaver  # noqa: PLC0415
    from langgraph.prebuilt import create_react_agent  # noqa: PLC0415

    from api.agent.tools import make_tools  # noqa: PLC0415

    return create_react_agent(
        model=chat_model,
        tools=make_tools(tfl_client=tfl_client),
        prompt=render(),
        checkpointer=InMemorySaver(),
    )
