"""Unit tests for :mod:`rag.upsert` (pgvector store)."""

from __future__ import annotations

from typing import Any

from llama_index.core.schema import NodeRelationship

from rag.parse import Chunk
from rag.upsert import (
    PAGE_UNKNOWN_SENTINEL,
    UPSERT_BATCH_SIZE,
    upsert_chunks,
    vector_id,
)


class _FakeVectorStore:
    def __init__(self) -> None:
        self.added: list[list[Any]] = []
        self.deleted: list[str] = []

    def add(self, nodes: list[Any], **_kwargs: Any) -> list[str]:
        self.added.append(list(nodes))
        return [node.id_ for node in nodes]

    def delete(self, ref_doc_id: str, **_kwargs: Any) -> None:
        self.deleted.append(ref_doc_id)


class _FakeEmbedding:
    async def aget_text_embedding_batch(
        self, texts: list[str], **_kwargs: Any
    ) -> list[list[float]]:
        return [[float(i)] * 4 for i, _ in enumerate(texts)]


def _build_chunks(n: int, *, doc_id: str = "doc") -> list[Chunk]:
    return [
        Chunk(
            doc_id=doc_id,
            doc_title="Doc Title",
            resolved_url="https://example.com/doc.pdf",
            chunk_index=i,
            section_title=f"Section {i}",
            page_start=i + 1,
            page_end=i + 2,
            text=f"chunk text {i}",
        )
        for i in range(n)
    ]


def test_vector_id_is_stable() -> None:
    a = vector_id("https://example.com/doc.pdf", 0)
    b = vector_id("https://example.com/doc.pdf", 0)
    c = vector_id("https://example.com/doc.pdf", 1)
    assert a == b
    assert a != c
    assert len(a) == 64


async def test_upsert_chunks_deletes_doc_when_delete_first() -> None:
    store = _FakeVectorStore()
    upserted = await upsert_chunks(
        vector_store=store,
        embed_model=_FakeEmbedding(),
        chunks=_build_chunks(3),
        doc_id="doc",
        delete_first=True,
    )
    assert upserted == 3
    assert store.deleted == ["doc"]


async def test_upsert_chunks_skips_delete_when_not_first() -> None:
    store = _FakeVectorStore()
    await upsert_chunks(
        vector_store=store,
        embed_model=_FakeEmbedding(),
        chunks=_build_chunks(3),
        doc_id="doc",
        delete_first=False,
    )
    assert store.deleted == []


async def test_upsert_chunks_node_shape() -> None:
    store = _FakeVectorStore()
    chunk = Chunk(
        doc_id="doc",
        doc_title="Doc Title",
        resolved_url="https://example.com/doc.pdf",
        chunk_index=0,
        section_title="",
        page_start=None,
        page_end=None,
        text="hello",
    )
    await upsert_chunks(
        vector_store=store,
        embed_model=_FakeEmbedding(),
        chunks=[chunk],
        doc_id="doc",
        delete_first=False,
    )
    node = store.added[0][0]
    assert node.id_ == vector_id("https://example.com/doc.pdf", 0)
    assert node.embedding == [0.0] * 4
    assert node.relationships[NodeRelationship.SOURCE].node_id == "doc"
    md = node.metadata
    assert md["doc_id"] == "doc"
    assert md["doc_title"] == "Doc Title"
    assert md["resolved_url"] == "https://example.com/doc.pdf"
    assert md["chunk_index"] == 0
    assert md["section_title"] == ""
    assert md["page_start"] == PAGE_UNKNOWN_SENTINEL
    assert md["page_end"] == PAGE_UNKNOWN_SENTINEL


async def test_upsert_chunks_batches_at_100() -> None:
    store = _FakeVectorStore()
    n = UPSERT_BATCH_SIZE * 2 + 50
    upserted = await upsert_chunks(
        vector_store=store,
        embed_model=_FakeEmbedding(),
        chunks=_build_chunks(n),
        doc_id="doc",
        delete_first=False,
    )
    assert upserted == n
    assert [len(batch) for batch in store.added] == [100, 100, 50]


async def test_upsert_chunks_empty_after_delete() -> None:
    store = _FakeVectorStore()
    upserted = await upsert_chunks(
        vector_store=store,
        embed_model=_FakeEmbedding(),
        chunks=[],
        doc_id="doc",
        delete_first=True,
    )
    assert upserted == 0
    assert store.deleted == ["doc"]
    assert store.added == []
