"""Unit tests for :mod:`rag.upsert`."""

from __future__ import annotations

from typing import Any

import pytest

from rag.parse import Chunk
from rag.upsert import (
    PAGE_UNKNOWN_SENTINEL,
    UPSERT_BATCH_SIZE,
    ensure_index,
    upsert_chunks,
    vector_id,
)


class _FakeIndex:
    def __init__(self) -> None:
        self.upsert_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []

    def upsert(self, *, vectors: list[dict[str, Any]], namespace: str) -> None:
        self.upsert_calls.append({"vectors": vectors, "namespace": namespace})

    def delete(self, *, delete_all: bool, namespace: str) -> None:
        self.delete_calls.append({"delete_all": delete_all, "namespace": namespace})


class _FakeClient:
    def __init__(self, *, existing: list[str] | None = None) -> None:
        self.existing = list(existing or [])
        self.create_calls: list[dict[str, Any]] = []
        self._index = _FakeIndex()

    def list_indexes(self) -> list[dict[str, str]]:
        return [{"name": n} for n in self.existing]

    def create_index(self, *, name: str, dimension: int, metric: str, spec: Any) -> None:
        self.create_calls.append(
            {"name": name, "dimension": dimension, "metric": metric, "spec": spec}
        )
        self.existing.append(name)

    def Index(self, name: str) -> _FakeIndex:  # noqa: N802 - matches Pinecone SDK
        del name
        return self._index


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
    assert len(a) == 64  # full sha256 hex


def test_ensure_index_skips_when_present() -> None:
    client = _FakeClient(existing=["tfl-strategy-docs"])
    ensure_index(client, name="tfl-strategy-docs")
    assert client.create_calls == []


def test_ensure_index_creates_when_missing() -> None:
    client = _FakeClient(existing=[])
    ensure_index(client, name="tfl-strategy-docs", cloud="aws", region="us-east-1")
    assert len(client.create_calls) == 1
    call = client.create_calls[0]
    assert call["name"] == "tfl-strategy-docs"
    assert call["dimension"] == 1536
    assert call["metric"] == "cosine"


def test_upsert_chunks_deletes_namespace_when_rollover() -> None:
    index = _FakeIndex()
    chunks = _build_chunks(3)
    vectors = [[float(i)] * 1536 for i in range(3)]
    upserted = upsert_chunks(
        index=index,
        chunks=chunks,
        vectors=vectors,
        namespace="doc",
        delete_namespace_first=True,
    )
    assert upserted == 3
    assert len(index.delete_calls) == 1
    assert index.delete_calls[0] == {"delete_all": True, "namespace": "doc"}


def test_upsert_chunks_skips_delete_when_not_rollover() -> None:
    index = _FakeIndex()
    chunks = _build_chunks(3)
    vectors = [[float(i)] * 1536 for i in range(3)]
    upsert_chunks(
        index=index,
        chunks=chunks,
        vectors=vectors,
        namespace="doc",
        delete_namespace_first=False,
    )
    assert index.delete_calls == []


def test_upsert_chunks_metadata_shape() -> None:
    index = _FakeIndex()
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
    upsert_chunks(
        index=index,
        chunks=[chunk],
        vectors=[[0.1] * 1536],
        namespace="doc",
        delete_namespace_first=False,
    )
    payload = index.upsert_calls[0]["vectors"][0]
    assert payload["id"] == vector_id("https://example.com/doc.pdf", 0)
    assert payload["values"] == [0.1] * 1536
    md = payload["metadata"]
    assert md["doc_id"] == "doc"
    assert md["doc_title"] == "Doc Title"
    assert md["resolved_url"] == "https://example.com/doc.pdf"
    assert md["chunk_index"] == 0
    assert md["section_title"] == ""
    assert md["page_start"] == PAGE_UNKNOWN_SENTINEL
    assert md["page_end"] == PAGE_UNKNOWN_SENTINEL
    assert md["text"] == "hello"


def test_upsert_chunks_batches_at_100() -> None:
    index = _FakeIndex()
    n = UPSERT_BATCH_SIZE * 2 + 50
    chunks = _build_chunks(n)
    vectors = [[float(i)] * 1536 for i in range(n)]
    upserted = upsert_chunks(
        index=index,
        chunks=chunks,
        vectors=vectors,
        namespace="doc",
        delete_namespace_first=False,
    )
    assert upserted == n
    assert [len(call["vectors"]) for call in index.upsert_calls] == [100, 100, 50]


def test_upsert_chunks_raises_when_lengths_differ() -> None:
    index = _FakeIndex()
    chunks = _build_chunks(3)
    vectors = [[0.1] * 1536, [0.2] * 1536]
    with pytest.raises(ValueError):
        upsert_chunks(
            index=index,
            chunks=chunks,
            vectors=vectors,
            namespace="doc",
            delete_namespace_first=False,
        )
