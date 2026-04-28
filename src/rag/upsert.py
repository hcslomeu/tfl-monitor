"""Pinecone upsert: create index if absent, namespace-per-doc, idempotent.

Per CLAUDE.md tech-stack the index is serverless (`cloud="aws"`,
`region="us-east-1"`), 1536 dimensions, cosine. One namespace per
``doc_id`` keeps the per-document delete simple — Pinecone serverless
free tier supports ``delete(delete_all=True, namespace=...)`` but not
metadata-filter delete.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any, Protocol

import logfire

from rag.config import (
    DEFAULT_PINECONE_CLOUD,
    DEFAULT_PINECONE_REGION,
    EMBEDDING_DIMENSIONS,
)
from rag.parse import Chunk

UPSERT_BATCH_SIZE = 100
PAGE_UNKNOWN_SENTINEL = -1


class _PineconeIndex(Protocol):
    def upsert(self, *, vectors: list[dict[str, Any]], namespace: str) -> Any: ...

    def delete(self, *, delete_all: bool, namespace: str) -> Any: ...


class _PineconeClient(Protocol):
    def list_indexes(self) -> Any: ...

    def create_index(self, *, name: str, dimension: int, metric: str, spec: Any) -> Any: ...

    def Index(self, name: str) -> _PineconeIndex: ...  # noqa: N802 - matches SDK


def vector_id(resolved_url: str, chunk_index: int) -> str:
    """Stable per-chunk id used as the Pinecone vector id."""
    return hashlib.sha256(f"{resolved_url}::{chunk_index}".encode()).hexdigest()


def _list_index_names(client: _PineconeClient) -> set[str]:
    raw = client.list_indexes()
    names: set[str] = set()
    for entry in raw:
        if isinstance(entry, dict) and "name" in entry:
            names.add(str(entry["name"]))
            continue
        name_attr = getattr(entry, "name", None)
        if isinstance(name_attr, str):
            names.add(name_attr)
            continue
        if isinstance(entry, str):
            names.add(entry)
    return names


def ensure_index(
    client: _PineconeClient,
    *,
    name: str,
    cloud: str = DEFAULT_PINECONE_CLOUD,
    region: str = DEFAULT_PINECONE_REGION,
) -> None:
    """Create the index if missing; idempotent."""
    if name in _list_index_names(client):
        return
    spec = _build_serverless_spec(cloud=cloud, region=region)
    client.create_index(
        name=name,
        dimension=EMBEDDING_DIMENSIONS,
        metric="cosine",
        spec=spec,
    )


def _build_serverless_spec(*, cloud: str, region: str) -> Any:
    from pinecone import ServerlessSpec

    return ServerlessSpec(cloud=cloud, region=region)


def upsert_chunks(
    *,
    index: _PineconeIndex,
    chunks: Iterable[Chunk],
    vectors: list[list[float]],
    namespace: str,
    delete_namespace_first: bool,
) -> int:
    """Upsert ``chunks`` (with their corresponding ``vectors``).

    Args:
        index: Pinecone index handle.
        chunks: Chunks aligned positionally with ``vectors``.
        vectors: Embedding vectors in the same order as ``chunks``.
        namespace: Pinecone namespace, conventionally the ``doc_id``.
        delete_namespace_first: When ``True`` clears the namespace
            before upserting (used when the resolved URL has rolled
            over for the same logical doc).

    Returns:
        Number of vectors successfully sent to Pinecone.
    """
    if delete_namespace_first:
        with logfire.span("rag.upsert.delete_namespace", namespace=namespace):
            index.delete(delete_all=True, namespace=namespace)

    payload: list[dict[str, Any]] = [
        {
            "id": vector_id(chunk.resolved_url, chunk.chunk_index),
            "values": vector,
            "metadata": {
                "doc_id": chunk.doc_id,
                "doc_title": chunk.doc_title,
                "resolved_url": chunk.resolved_url,
                "chunk_index": chunk.chunk_index,
                "section_title": chunk.section_title,
                "page_start": chunk.page_start
                if chunk.page_start is not None
                else PAGE_UNKNOWN_SENTINEL,
                "page_end": chunk.page_end if chunk.page_end is not None else PAGE_UNKNOWN_SENTINEL,
                "text": chunk.text,
            },
        }
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]

    upserted = 0
    for start in range(0, len(payload), UPSERT_BATCH_SIZE):
        batch = payload[start : start + UPSERT_BATCH_SIZE]
        with logfire.span(
            "rag.upsert",
            namespace=namespace,
            n_vectors=len(batch),
            batch_index=start // UPSERT_BATCH_SIZE,
        ):
            index.upsert(vectors=batch, namespace=namespace)
        upserted += len(batch)
    return upserted
