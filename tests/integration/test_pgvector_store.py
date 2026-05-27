"""Integration test for the pgvector store against a real Postgres.

Exercises :func:`rag.vectorstore.build_vector_store` end to end — dialect
load, the ORM delete path, and the similarity query — which fake-backed
unit tests cannot cover. These are exactly the runtime failures that
reached production when the universal lock pinned SQLAlchemy below 2.0
(see ADR 008).

The embedding is a deterministic stand-in, not Bedrock: the point is to
validate the store/SQLAlchemy plumbing without needing AWS credentials in
CI. Runs only under ``-m integration`` against the Compose
``pgvector/pgvector:pg16`` service, on an isolated test table that is
dropped afterwards.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("llama_index.vector_stores.postgres")

from llama_index.core.vector_stores.types import VectorStoreQuery  # noqa: E402

from rag.config import RagSettings  # noqa: E402
from rag.parse import Chunk  # noqa: E402
from rag.upsert import upsert_chunks  # noqa: E402
from rag.vectorstore import build_vector_store  # noqa: E402

_DSN = os.environ.get("RAG_DATABASE_URL") or os.environ.get("DATABASE_URL")
_TEST_TABLE = "tfl_strategy_docs_itest"
_TEST_DOC_ID = "itest_doc"
_DIMS = 1024

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _DSN,
        reason="RAG_DATABASE_URL / DATABASE_URL not set; skipping pgvector integration test",
    ),
]


class _FakeEmbedding:
    """Deterministic embedding: one-hot vectors keyed on chunk index."""

    def __init__(self, dims: int) -> None:
        self._dims = dims

    def vector(self, index: int) -> list[float]:
        vec = [0.0] * self._dims
        vec[index % self._dims] = 1.0
        return vec

    async def aget_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.vector(i) for i, _ in enumerate(texts)]


def _settings() -> RagSettings:
    # Override only the table so the test never touches the real corpus
    # table; the DSN still comes from the environment.
    return RagSettings(pgvector_table=_TEST_TABLE, embedding_dimensions=_DIMS)


def _chunk(index: int) -> Chunk:
    return Chunk(
        doc_id=_TEST_DOC_ID,
        doc_title="Integration",
        resolved_url="https://example.com/itest.pdf",
        chunk_index=index,
        text=f"integration chunk {index}",
        section_title="S",
        page_start=1,
        page_end=1,
    )


@pytest.fixture
async def _clean_table() -> AsyncIterator[None]:
    yield
    # Drop the isolated test table after the run so re-runs start fresh.
    with psycopg.connect(_DSN, connect_timeout=20) as conn, conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS public.data_{_TEST_TABLE} CASCADE")
        conn.commit()


async def test_build_vector_store_upsert_and_query_roundtrip(_clean_table: Any) -> None:
    settings = _settings()
    store = build_vector_store(settings)
    embed = _FakeEmbedding(settings.embedding_dimensions)

    upserted = await upsert_chunks(
        vector_store=store,
        embed_model=embed,
        chunks=[_chunk(0), _chunk(1)],
        doc_id=_TEST_DOC_ID,
        delete_first=True,
    )
    assert upserted == 2

    query = VectorStoreQuery(query_embedding=embed.vector(0), similarity_top_k=2)

    sync_result = store.query(query)
    assert sync_result.nodes
    assert all(node.metadata["doc_id"] == _TEST_DOC_ID for node in sync_result.nodes)

    # The agent retriever uses the async path (asyncpg); cover it too.
    async_result = await store.aquery(query)
    assert async_result.nodes
