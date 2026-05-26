"""Shared pgvector store + embedding factories for ingest and retrieval.

Both the ingestion pipeline (:mod:`rag.ingest`) and the agent retriever
(:mod:`api.agent.rag`) read/write the same LlamaIndex-managed pgvector
table, so the store construction lives here to keep the two sides in
lockstep on table name, schema, and embedding dimensions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rag.config import RagSettings
from rag.embeddings import TitanEmbedding

if TYPE_CHECKING:
    from llama_index.vector_stores.postgres import PGVectorStore

# Cosine HNSW: matches the OpenAI/Pinecone cosine metric the corpus used
# before the migration, so retrieval ranking stays comparable.
_HNSW_KWARGS = {
    "hnsw_m": 16,
    "hnsw_ef_construction": 64,
    "hnsw_ef_search": 40,
    "hnsw_dist_method": "vector_cosine_ops",
}


def build_embedding(settings: RagSettings) -> TitanEmbedding:
    """Build the Bedrock Titan embedding from settings."""
    return TitanEmbedding(
        model_name=settings.embedding_model,
        region=settings.bedrock_region,
        dimensions=settings.embedding_dimensions,
    )


def build_vector_store(settings: RagSettings) -> PGVectorStore:
    """Build the pgvector store, creating the table/index on first use.

    Uses ``psycopg`` (v3) for the synchronous engine and ``asyncpg`` for
    the async engine. The DSN must point at a direct/session Postgres
    endpoint (port 5432): ``asyncpg`` prepared statements are rejected by
    the Supabase transaction pooler (port 6543).
    """
    from llama_index.vector_stores.postgres import PGVectorStore  # noqa: PLC0415

    # Swap only the scheme; keep the (already URL-encoded) credentials and
    # host verbatim so reserved chars in a Supabase password survive.
    _, _, rest = settings.vector_database_url.partition("://")
    return PGVectorStore.from_params(
        connection_string=f"postgresql+psycopg://{rest}",
        async_connection_string=f"postgresql+asyncpg://{rest}",
        table_name=settings.pgvector_table,
        schema_name=settings.pgvector_schema,
        embed_dim=settings.embedding_dimensions,
        hnsw_kwargs=_HNSW_KWARGS,
    )
