"""Upsert parsed chunks into the LlamaIndex-managed pgvector store.

Idempotency is delete-then-insert per document: each changed doc clears
its existing rows (``delete(ref_doc_id=doc_id)``) before re-inserting, so
a re-run never duplicates or strands stale chunks. The page sentinel
keeps ``page_start``/``page_end`` as integers in metadata; the retriever
maps ``-1`` back to ``None``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

import logfire

from rag.parse import Chunk

if TYPE_CHECKING:
    from llama_index.core.embeddings import BaseEmbedding
    from llama_index.core.vector_stores.types import BasePydanticVectorStore

UPSERT_BATCH_SIZE = 100
PAGE_UNKNOWN_SENTINEL = -1


def vector_id(resolved_url: str, chunk_index: int) -> str:
    """Stable per-chunk id (deterministic across re-ingestion runs)."""
    return hashlib.sha256(f"{resolved_url}::{chunk_index}".encode()).hexdigest()


def _chunk_to_node(chunk: Chunk, *, doc_id: str) -> Any:
    from llama_index.core.schema import (  # noqa: PLC0415
        NodeRelationship,
        RelatedNodeInfo,
        TextNode,
    )

    node = TextNode(
        id_=vector_id(chunk.resolved_url, chunk.chunk_index),
        text=chunk.text,
        metadata={
            # Keyed on the doc_id argument (the deletion key), not
            # chunk.doc_id, so metadata and delete() can never diverge.
            "doc_id": doc_id,
            "doc_title": chunk.doc_title,
            "resolved_url": chunk.resolved_url,
            "chunk_index": chunk.chunk_index,
            "section_title": chunk.section_title,
            "page_start": chunk.page_start
            if chunk.page_start is not None
            else PAGE_UNKNOWN_SENTINEL,
            "page_end": chunk.page_end if chunk.page_end is not None else PAGE_UNKNOWN_SENTINEL,
        },
    )
    # SOURCE relationship becomes the stored ``doc_id`` that delete() keys on.
    node.relationships[NodeRelationship.SOURCE] = RelatedNodeInfo(node_id=doc_id)
    return node


async def upsert_chunks(
    *,
    vector_store: BasePydanticVectorStore,
    embed_model: BaseEmbedding,
    chunks: Iterable[Chunk],
    doc_id: str,
    delete_first: bool = True,
) -> int:
    """Embed ``chunks`` and upsert them under ``doc_id``.

    Args:
        vector_store: LlamaIndex pgvector store handle.
        embed_model: Embedding model used to vectorise chunk text.
        chunks: Chunks to upsert (all belonging to ``doc_id``).
        doc_id: Document identifier; rows are keyed on it for deletion.
        delete_first: Clear the document's existing rows before insert
            (delete-then-insert idempotency).

    Returns:
        Number of chunks upserted.
    """
    chunk_list = list(chunks)
    # Embed BEFORE deleting: if embedding raises, the existing rows stay
    # intact instead of leaving the document empty until the next success.
    # ``aget_text_embedding_batch`` fans the per-chunk Titan calls out
    # concurrently, so hundreds of chunks don't serialise into a long stall.
    nodes = [_chunk_to_node(chunk, doc_id=doc_id) for chunk in chunk_list]
    if nodes:
        embeddings = await embed_model.aget_text_embedding_batch(
            [chunk.text for chunk in chunk_list]
        )
        for node, embedding in zip(nodes, embeddings, strict=True):
            node.embedding = embedding

    if delete_first:
        with logfire.span("rag.upsert.delete_doc", doc_id=doc_id):
            vector_store.delete(ref_doc_id=doc_id)

    for start in range(0, len(nodes), UPSERT_BATCH_SIZE):
        batch = nodes[start : start + UPSERT_BATCH_SIZE]
        with logfire.span(
            "rag.upsert",
            doc_id=doc_id,
            n_vectors=len(batch),
            batch_index=start // UPSERT_BATCH_SIZE,
        ):
            vector_store.add(batch)
    return len(nodes)
