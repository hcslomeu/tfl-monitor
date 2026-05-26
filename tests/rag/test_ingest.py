"""Unit tests for :mod:`rag.ingest`."""

from __future__ import annotations

import asyncio
import hashlib
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
from tests.rag.test_upsert import (  # type: ignore[import-not-found]
    _FakeEmbedding,
    _FakeVectorStore,
)

_PDF_BYTES = b"%PDF-1.4 fake content for unit tests\n"


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
    def handler(_request: httpx.Request) -> httpx.Response:
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


def _build_httpx_factory_returning_304() -> Any:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(304)

    transport = httpx.MockTransport(handler)
    return lambda: httpx.AsyncClient(transport=transport)


def _build_fakes() -> tuple[_FakeEmbedding, _FakeVectorStore, _FakeConverter, _FakeChunker]:
    converter = _FakeConverter(document=object())
    chunker = _FakeChunker(
        [
            _build_fake_chunk("first chunk", headings=["Intro"], pages=[1]),
            _build_fake_chunk("second chunk", headings=["Body"], pages=[2, 3]),
        ]
    )
    return _FakeEmbedding(), _FakeVectorStore(), converter, chunker


def _run(
    *,
    sources_path: Path,
    data_dir: Path,
    cache_path: Path,
    embed: _FakeEmbedding,
    store: _FakeVectorStore,
    converter: _FakeConverter,
    chunker: Any,
    httpx_factory: Any | None = None,
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
            embedding_factory=lambda _settings: embed,
            vector_store_factory=lambda _settings: store,
            httpx_factory=httpx_factory or _build_httpx_factory(),
            docling_converter=converter,
            docling_chunker=chunker,
        )
    )


def test_run_ingestion_end_to_end_with_fakes(tmp_path: Path) -> None:
    sources_path = tmp_path / "sources.json"
    _seed_sources(sources_path)
    embed, store, converter, chunker = _build_fakes()

    upserted = _run(
        sources_path=sources_path,
        data_dir=tmp_path / "data",
        cache_path=tmp_path / "cache" / "sources_state.json",
        embed=embed,
        store=store,
        converter=converter,
        chunker=chunker,
    )

    assert upserted == 2
    assert len(store.added) == 1
    assert len(store.added[0]) == 2
    # Delete-then-insert idempotency: the doc is cleared before insert.
    assert store.deleted == ["sample"]


def test_run_ingestion_dry_run_skips_upsert(tmp_path: Path) -> None:
    sources_path = tmp_path / "sources.json"
    _seed_sources(sources_path)
    embed, store, converter, chunker = _build_fakes()

    upserted = _run(
        sources_path=sources_path,
        data_dir=tmp_path / "data",
        cache_path=tmp_path / "cache" / "sources_state.json",
        embed=embed,
        store=store,
        converter=converter,
        chunker=chunker,
        dry_run=True,
    )

    assert upserted == 0
    # The vector store factory is never invoked on a dry run.
    assert store.added == []
    assert store.deleted == []


def test_run_ingestion_skips_parse_and_embed_when_unchanged(tmp_path: Path) -> None:
    """HTTP 304 cache hit -> skip parse/embed/upsert (cost-leak fix)."""
    sources_path = tmp_path / "sources.json"
    _seed_sources(sources_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    target = data_dir / "sample.pdf"
    target.write_bytes(_PDF_BYTES)
    cache_path = tmp_path / "cache" / "sources_state.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "sample": {
                    "resolved_url": "https://example.com/sample.pdf",
                    "etag": '"abc"',
                    "last_modified": "Wed, 21 Oct 2026 07:28:00 GMT",
                    "sha256": hashlib.sha256(_PDF_BYTES).hexdigest(),
                    "fetched_at": "2026-04-01T00:00:00+00:00",
                }
            }
        )
    )

    embed, store, converter, chunker = _build_fakes()
    upserted = _run(
        sources_path=sources_path,
        data_dir=data_dir,
        cache_path=cache_path,
        embed=embed,
        store=store,
        converter=converter,
        chunker=chunker,
        httpx_factory=_build_httpx_factory_returning_304(),
    )

    assert upserted == 0
    assert store.added == []
    assert store.deleted == []


class _ExplodingChunker:
    """Chunker that raises mid-pipeline to verify partial-failure exit code."""

    def chunk(self, _document: object) -> list[object]:
        raise RuntimeError("simulated parse failure")


def test_run_ingestion_aggregates_per_doc_failures_and_exits_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sources_path = tmp_path / "sources.json"
    _seed_sources(sources_path)
    embed, store, converter, _ = _build_fakes()

    with pytest.raises(SystemExit) as excinfo:
        _run(
            sources_path=sources_path,
            data_dir=tmp_path / "data",
            cache_path=tmp_path / "cache" / "sources_state.json",
            embed=embed,
            store=store,
            converter=converter,
            chunker=_ExplodingChunker(),
        )
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "1 failure" in err
    assert "sample" in err
    assert "simulated parse failure" in err
    assert store.added == []


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

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/landing":
            return httpx.Response(200, text='<a href="https://example.com/sample.pdf">x</a>')
        return httpx.Response(200, content=_PDF_BYTES)

    transport = httpx.MockTransport(handler)
    embed, store, converter, chunker = _build_fakes()
    asyncio.run(
        _amain(
            force_refetch=False,
            dry_run=False,
            refresh_urls=True,
            sources_path=sources_path,
            data_dir=tmp_path / "data",
            cache_path=tmp_path / "cache" / "sources_state.json",
            embedding_factory=lambda _settings: embed,
            vector_store_factory=lambda _settings: store,
            httpx_factory=lambda: httpx.AsyncClient(transport=transport),
            docling_converter=converter,
            docling_chunker=chunker,
        )
    )

    rewritten = json.loads(sources_path.read_text())
    assert rewritten[0]["resolved_url"] == "https://example.com/sample.pdf"
