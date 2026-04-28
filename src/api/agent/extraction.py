"""Pydantic AI line-id normaliser.

Maps free-text line names ("Lizzy", "Lizzie", "Elizabeth Line") to the
canonical TfL ``line_id``. Used inside ``query_line_reliability`` when
the LLM-supplied ``line_id`` is not already a canonical token.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, get_args

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


class LineId(BaseModel):
    """Canonical line-id wrapper used as the Pydantic AI output type."""

    line_id: CanonicalLineId


@lru_cache(maxsize=1)
def _normaliser() -> Agent[None, LineId]:
    """Return the singleton Haiku-backed extraction agent."""
    return Agent(
        "anthropic:claude-3-5-haiku-latest",
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
    except Exception:  # noqa: BLE001 — boundary; LangSmith captures
        return None
    return result.output.line_id
