"""Pydantic settings for RAG ingestion.

Loads OpenAI + Pinecone credentials and the index/embedding-model
defaults used by :mod:`rag.ingest`. Five fields total — well under the
≥15 trigger that would justify nested ``BaseSettings`` (CLAUDE.md
§"Principle #1" rule 5).
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PINECONE_INDEX = "tfl-strategy-docs"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
DEFAULT_PINECONE_CLOUD = "aws"
DEFAULT_PINECONE_REGION = "us-east-1"


class RagSettings(BaseSettings):
    """RAG ingestion configuration loaded from the process environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: SecretStr
    pinecone_api_key: SecretStr
    pinecone_index: str = DEFAULT_PINECONE_INDEX
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    pinecone_cloud: str = DEFAULT_PINECONE_CLOUD
    pinecone_region: str = DEFAULT_PINECONE_REGION


def load_settings() -> RagSettings:
    """Load and validate :class:`RagSettings` from the environment.

    Raises:
        SystemExit: ``code=2`` when required secrets are missing or
            malformed. Fail-loud per the TM-D4 briefing.
    """
    try:
        return RagSettings()  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001 - boundary
        raise SystemExit(f"RAG settings missing or invalid: {exc!s}") from None
