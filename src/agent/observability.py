"""LangSmith configuration helper.

LangGraph and Pydantic AI pick up ``LANGSMITH_*`` environment variables on
their own. This module only validates that the environment is coherent and
reports status to the logger.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def validate_langsmith_env() -> bool:
    """Return ``True`` when LangSmith tracing is fully configured."""
    if os.getenv("LANGSMITH_TRACING", "").lower() != "true":
        logger.info("LangSmith tracing disabled (set LANGSMITH_TRACING=true to enable)")
        return False
    if not os.getenv("LANGSMITH_API_KEY"):
        logger.warning("LANGSMITH_TRACING=true but LANGSMITH_API_KEY is missing")
        return False
    project = os.getenv("LANGSMITH_PROJECT", "tfl-monitor")
    logger.info("LangSmith tracing enabled for project=%s", project)
    return True
