"""Unit tests for :mod:`rag.ingest`."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from rag.ingest import _amain
from rag.sources import write_sources
from tests.rag.test_parse import (  # type: ignore[import-not-found]
    _build_fake_chunk,
    _FakeChunker,
    _FakeConverter,
)
from tests.rag.test_upsert import _FakeClient  # type: ignore[import-not-found]

_PDF_BYTES = b"%PDF-1.4 fake content for unit tests\n"


class _FakeEmbeddingItem:
    def __init__(self, vector: list[float]) -> None:
        self.embedding = vector


class _FakeEmbeddingResponse:
    def __init__(self, count: int) -> None:
        self.data = [_FakeEmbeddingItem([float(i)] * 1536) for i in range(count)]


class _FakeEmbeddings:
    async def create(self, *, model: str, input: list[str]) -> _FakeEmbeddingResponse:
        del model
        return _FakeEmbeddingResponse(len(input))


class _FakeOpenAI:
    def __init__(self) -> None:
        self.embeddings = _FakeEmbeddings()


def _seed_sources(path: Path) -> None:
    """Write a single-source JSON file the orchestrator can load."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "name": "Sample Doc",
                    "doc_id": "sample",
                    "landing_url": "https://example.com/landing",
                    "discovery_regex": r"sample\.pdf$",
                    "resolved_url": "https://example.com/sample.pdf",
                }
            ],
            indent=2,
        )
        + "\n",
    )


def _build_httpx_factory() -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            content=_PDF_BYTES,
            headers={
                "ETag": '"abc"',
                "Last-Modified": "Wed, 21 Oct 2026 07:28:00 GMT",
            },
        )

    transport = httpx.MockTransport(handler)
    return lambda: httpx.AsyncClient(transport=transport)


def _build_fakes() -> tuple[_FakeOpenAI, _FakeClient, _FakeConverter, _FakeChunker]:
    openai_client = _FakeOpenAI()
    pinecone_client = _FakeClient(existing=["tfl-strategy-docs"])
    converter = _FakeConverter(document=object())
    chunker = _FakeChunker(
        [
            _build_fake_chunk("first chunk", headings=["Intro"], pages=[1]),
            _build_fake_chunk("second chunk", headings=["Body"], pages=[2, 3]),
        ]
    )
    return openai_client, pinecone_client, converter, chunker


def _run(
    *,
    sources_path: Path,
    data_dir: Path,
    cache_path: Path,
    pinecone_client: _FakeClient,
    openai_client: _FakeOpenAI,
    converter: _FakeConverter,
    chunker: _FakeChunker,
    dry_run: bool = False,
    force_refetch: bool = False,
    refresh_urls: bool = False,
) -> int:
    return asyncio.run(
        _amain(
            force_refetch=force_refetch,
            dry_run=dry_run,
            refresh_urls=refresh_urls,
            sources_path=sources_path,
            data_dir=data_dir,
            cache_path=cache_path,
            pinecone_factory=lambda _settings: pinecone_client,
            openai_factory=lambda _settings: openai_client,
            httpx_factory=_build_httpx_factory(),
            docling_converter=converter,
            docling_chunker=chunker,
        )
    )


def test_run_ingestion_end_to_end_with_fakes(tmp_path: Path) -> None:
    sources_path = tmp_path / "sources.json"
    _seed_sources(sources_path)
    openai_client, pinecone_client, converter, chunker = _build_fakes()

    upserted = _run(
        sources_path=sources_path,
        data_dir=tmp_path / "data",
        cache_path=tmp_path / "cache" / "sources_state.json",
        pinecone_client=pinecone_client,
        openai_client=openai_client,
        converter=converter,
        chunker=chunker,
    )

    assert upserted == 2
    index = pinecone_client.Index("tfl-strategy-docs")
    assert len(index.upsert_calls) == 1
    assert index.upsert_calls[0]["namespace"] == "sample"
    assert len(index.upsert_calls[0]["vectors"]) == 2
    # No rollover on first run → no namespace delete.
    assert index.delete_calls == []


def test_run_ingestion_dry_run_skips_upsert(tmp_path: Path) -> None:
    sources_path = tmp_path / "sources.json"
    _seed_sources(sources_path)
    openai_client, pinecone_client, converter, chunker = _build_fakes()

    upserted = _run(
        sources_path=sources_path,
        data_dir=tmp_path / "data",
        cache_path=tmp_path / "cache" / "sources_state.json",
        pinecone_client=pinecone_client,
        openai_client=openai_client,
        converter=converter,
        chunker=chunker,
        dry_run=True,
    )

    assert upserted == 0
    index = pinecone_client.Index("tfl-strategy-docs")
    assert index.upsert_calls == []
    assert index.delete_calls == []


def test_run_ingestion_rollover_triggers_namespace_delete(tmp_path: Path) -> None:
    sources_path = tmp_path / "sources.json"
    _seed_sources(sources_path)
    cache_path = tmp_path / "cache" / "sources_state.json"
    cache_path.parent.mkdir(parents=True)
    # Pre-seed cache with a *different* resolved URL → rollover.
    cache_path.write_text(
        json.dumps(
            {
                "sample": {
                    "resolved_url": "https://example.com/old-sample.pdf",
                    "etag": '"old"',
                    "last_modified": "Mon, 01 Jan 2025 00:00:00 GMT",
                    "sha256": "old",
                    "fetched_at": "2025-01-01T00:00:00+00:00",
                }
            }
        )
    )

    openai_client, pinecone_client, converter, chunker = _build_fakes()
    _run(
        sources_path=sources_path,
        data_dir=tmp_path / "data",
        cache_path=cache_path,
        pinecone_client=pinecone_client,
        openai_client=openai_client,
        converter=converter,
        chunker=chunker,
    )

    index = pinecone_client.Index("tfl-strategy-docs")
    assert index.delete_calls == [{"delete_all": True, "namespace": "sample"}]


def test_run_ingestion_same_url_skips_rollover_delete(tmp_path: Path) -> None:
    """Identical resolved_url between runs → no namespace wipe (idempotent)."""
    sources_path = tmp_path / "sources.json"
    _seed_sources(sources_path)
    cache_path = tmp_path / "cache" / "sources_state.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "sample": {
                    "resolved_url": "https://example.com/sample.pdf",  # SAME url
                    "etag": '"abc"',
                    "last_modified": "Wed, 21 Oct 2026 07:28:00 GMT",
                    "sha256": "deadbeef",
                    "fetched_at": "2026-04-01T00:00:00+00:00",
                }
            }
        )
    )

    openai_client, pinecone_client, converter, chunker = _build_fakes()
    _run(
        sources_path=sources_path,
        data_dir=tmp_path / "data",
        cache_path=cache_path,
        pinecone_client=pinecone_client,
        openai_client=openai_client,
        converter=converter,
        chunker=chunker,
    )

    index = pinecone_client.Index("tfl-strategy-docs")
    # No delete fired — re-upserting onto stable ids overwrites in place.
    assert index.delete_calls == []
    # Upsert still happened.
    assert len(index.upsert_calls) == 1


class _ExplodingChunker:
    """Chunker that raises mid-pipeline so we can verify partial-failure exit code."""

    def chunk(self, _document: object) -> list[object]:
        raise RuntimeError("simulated parse failure")


def test_run_ingestion_aggregates_per_doc_failures_and_exits_nonzero(
    tmp_path: Path,
) -> None:
    sources_path = tmp_path / "sources.json"
    _seed_sources(sources_path)
    openai_client, pinecone_client, converter, _ = _build_fakes()

    with pytest.raises(SystemExit) as excinfo:
        _run(
            sources_path=sources_path,
            data_dir=tmp_path / "data",
            cache_path=tmp_path / "cache" / "sources_state.json",
            pinecone_client=pinecone_client,
            openai_client=openai_client,
            converter=converter,
            chunker=_ExplodingChunker(),  # type: ignore[arg-type]
        )
    msg = str(excinfo.value)
    assert "1 failure" in msg
    assert "sample" in msg
    assert "simulated parse failure" in msg
    # Upsert never reached for the failing doc.
    index = pinecone_client.Index("tfl-strategy-docs")
    assert index.upsert_calls == []


def test_run_ingestion_missing_pinecone_key_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    sources_path = tmp_path / "sources.json"
    _seed_sources(sources_path)
    openai_client, pinecone_client, converter, chunker = _build_fakes()

    with pytest.raises(SystemExit) as excinfo:
        _run(
            sources_path=sources_path,
            data_dir=tmp_path / "data",
            cache_path=tmp_path / "cache" / "sources_state.json",
            pinecone_client=pinecone_client,
            openai_client=openai_client,
            converter=converter,
            chunker=chunker,
        )
    assert "RAG settings missing or invalid" in str(excinfo.value)


def test_run_ingestion_refresh_urls_rewrites_sources(tmp_path: Path) -> None:
    sources_path = tmp_path / "sources.json"
    write_sources(
        sources_path,
        [
            __import__("rag.sources", fromlist=["PdfSource"]).PdfSource(
                name="Sample",
                doc_id="sample",
                landing_url="https://example.com/landing",
                discovery_regex=r"sample\.pdf$",
                resolved_url="https://example.com/old-sample.pdf",
            )
        ],
    )

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/landing":
            return httpx.Response(
                200,
                text='<a href="https://example.com/sample.pdf">x</a>',
            )
        return httpx.Response(200, content=_PDF_BYTES)

    transport = httpx.MockTransport(handler)
    openai_client, pinecone_client, converter, chunker = _build_fakes()
    asyncio.run(
        _amain(
            force_refetch=False,
            dry_run=False,
            refresh_urls=True,
            sources_path=sources_path,
            data_dir=tmp_path / "data",
            cache_path=tmp_path / "cache" / "sources_state.json",
            pinecone_factory=lambda _settings: pinecone_client,
            openai_factory=lambda _settings: openai_client,
            httpx_factory=lambda: httpx.AsyncClient(transport=transport),
            docling_converter=converter,
            docling_chunker=chunker,
        )
    )

    rewritten = json.loads(sources_path.read_text())
    assert rewritten[0]["resolved_url"] == "https://example.com/sample.pdf"
