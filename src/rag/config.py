"""Pydantic settings for RAG ingestion + retrieval.

Configures the Bedrock Titan embedding model and the pgvector
connection used by :mod:`rag.ingest` and the agent retriever. Bedrock
credentials come from the boto3 standard chain (``AWS_*`` env vars), so
there are no API keys here — the migration off OpenAI/Pinecone means the
only required runtime input is a Postgres connection string.
"""

from __future__ import annotations

import logfire
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BEDROCK_REGION = "eu-west-2"
DEFAULT_EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
DEFAULT_EMBEDDING_DIMENSIONS = 1024
DEFAULT_PGVECTOR_TABLE = "tfl_strategy_docs"
DEFAULT_PGVECTOR_SCHEMA = "public"


class RagSettings(BaseSettings):
    """RAG configuration loaded from the process environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bedrock_region: str = DEFAULT_BEDROCK_REGION
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    pgvector_table: str = DEFAULT_PGVECTOR_TABLE
    pgvector_schema: str = DEFAULT_PGVECTOR_SCHEMA
    # Direct (non-pooled) connection for pgvector. asyncpg prepared
    # statements break against the Supabase transaction pooler (port
    # 6543); point RAG at the direct/session endpoint (port 5432).
    # Falls back to DATABASE_URL when unset (local dev uses one DSN).
    rag_database_url: SecretStr | None = None
    database_url: SecretStr | None = None

    @property
    def vector_database_url(self) -> str:
        """Return the DSN used for the pgvector store.

        An empty ``RAG_DATABASE_URL`` falls back to ``DATABASE_URL``:
        ``SecretStr("")`` is truthy, so the empty value is unwrapped and
        treated as unset rather than short-circuiting the fallback.

        Raises:
            ValueError: When neither ``RAG_DATABASE_URL`` nor
                ``DATABASE_URL`` resolves to a non-empty DSN.
        """
        rag = self.rag_database_url.get_secret_value() if self.rag_database_url is not None else ""
        db = self.database_url.get_secret_value() if self.database_url is not None else ""
        url = rag or db
        if not url:
            raise ValueError("Neither RAG_DATABASE_URL nor DATABASE_URL is set")
        return url


def load_settings() -> RagSettings:
    """Load and validate :class:`RagSettings` from the environment.

    Raises:
        SystemExit: ``code=2`` when the settings are malformed. Fail-loud
            keeps a misconfigured ingestion run from silently no-op'ing.
    """
    try:
        return RagSettings()
    except Exception as exc:  # noqa: BLE001 - boundary
        logfire.error("rag_settings_invalid", error=str(exc))
        raise SystemExit(2) from None
