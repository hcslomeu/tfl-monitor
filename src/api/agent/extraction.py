"""Pydantic AI line-id normaliser.

Maps free-text line names ("Lizzy", "Lizzie", "Elizabeth Line") to the
canonical TfL ``line_id``. Used inside ``query_line_reliability`` when
the LLM-supplied ``line_id`` is not already a canonical token.

Backend selection mirrors :mod:`api.agent.graph`: when
``BEDROCK_REGION`` is set the normaliser runs Haiku via Bedrock,
otherwise it falls back to Anthropic direct for local dev.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal, get_args

import logfire
from pydantic import BaseModel
from pydantic_ai import Agent

CanonicalLineId = Literal[
    "bakerloo",
    "central",
    "circle",
    "district",
    "hammersmith-city",
    "jubilee",
    "metropolitan",
    "northern",
    "piccadilly",
    "victoria",
    "waterloo-city",
    "elizabeth",
]

_CANONICAL: frozenset[str] = frozenset(get_args(CanonicalLineId))
DEFAULT_BEDROCK_HAIKU_MODEL = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
DEFAULT_ANTHROPIC_HAIKU_MODEL = "anthropic:claude-3-5-haiku-latest"


class LineId(BaseModel):
    """Canonical line-id wrapper used as the Pydantic AI output type."""

    line_id: CanonicalLineId


def _model_string() -> str:
    """Return the pydantic-ai model identifier for the active backend."""
    if os.environ.get("BEDROCK_REGION"):
        return "bedrock:" + os.environ.get("BEDROCK_HAIKU_MODEL_ID", DEFAULT_BEDROCK_HAIKU_MODEL)
    return DEFAULT_ANTHROPIC_HAIKU_MODEL


@lru_cache(maxsize=1)
def _normaliser() -> Agent[None, LineId]:
    """Return the singleton Haiku-backed extraction agent."""
    return Agent(
        _model_string(),
        output_type=LineId,
        instructions=(
            "Map the user's mention of a London Underground or Elizabeth "
            "line to its canonical line_id. Never invent unfamiliar lines."
        ),
    )


async def normalise_line_id(text: str) -> str | None:
    """Return the canonical ``line_id`` for ``text`` or ``None`` if unknown.

    Pass-through when ``text`` is already a canonical token; otherwise
    delegates to a Haiku-backed Pydantic AI agent. Any exception raised
    by the LLM call is swallowed and surfaced as ``None``; LangSmith
    captures the underlying error for debugging.

    Args:
        text: Free-text line reference (e.g. ``"Lizzy line"``).

    Returns:
        Canonical ``line_id`` string or ``None`` when the line cannot
        be identified.
    """
    if text in _CANONICAL:
        return text
    try:
        result = await _normaliser().run(text)
    except Exception:  # noqa: BLE001 — boundary; surface as None
        # LangSmith captures the underlying SDK error. Mirror it on
        # Logfire so on-call has timing + structured attributes locally.
        logfire.exception("agent.normalise_line_id.failed", text=text)
        return None
    return result.output.line_id
