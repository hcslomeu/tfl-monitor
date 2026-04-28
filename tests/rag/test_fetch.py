"""Unit tests for :mod:`rag.fetch`."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from rag.fetch import fetch_pdfs, load_cache
from rag.sources import PdfSource

_PDF_BYTES = b"%PDF-1.4 fake content for unit tests\n"
_ETAG = '"abc123"'
_LAST_MODIFIED = "Wed, 21 Oct 2026 07:28:00 GMT"


def _make_source() -> PdfSource:
    return PdfSource(
        name="Sample",
        doc_id="sample",
        landing_url="https://example.com/landing",
        discovery_regex=r"sample\.pdf$",
        resolved_url="https://example.com/sample.pdf",
    )


def _client(handler: callable) -> httpx.AsyncClient:  # type: ignore[valid-type]
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_pdfs_writes_file_and_cache_on_200(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            content=_PDF_BYTES,
            headers={"ETag": _ETAG, "Last-Modified": _LAST_MODIFIED},
        )

    data_dir = tmp_path / "strategy_docs"
    cache_path = tmp_path / "cache" / "sources_state.json"
    async with _client(handler) as client:
        results = await fetch_pdfs(
            [_make_source()],
            client=client,
            data_dir=data_dir,
            cache_path=cache_path,
        )
    [r] = results
    assert r.changed is True
    assert r.local_path.exists()
    assert r.local_path.read_bytes() == _PDF_BYTES
    assert r.sha256 == hashlib.sha256(_PDF_BYTES).hexdigest()
    assert r.etag == _ETAG
    assert r.last_modified == _LAST_MODIFIED
    assert "If-None-Match" not in requests[0].headers

    cache = load_cache(cache_path)
    assert cache["sample"]["etag"] == _ETAG
    assert cache["sample"]["sha256"] == r.sha256


async def test_fetch_pdfs_skips_on_304(tmp_path: Path) -> None:
    data_dir = tmp_path / "strategy_docs"
    cache_path = tmp_path / "cache" / "sources_state.json"
    data_dir.mkdir(parents=True)
    target = data_dir / "sample.pdf"
    target.write_bytes(_PDF_BYTES)
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "sample": {
                    "resolved_url": "https://example.com/sample.pdf",
                    "etag": _ETAG,
                    "last_modified": _LAST_MODIFIED,
                    "sha256": hashlib.sha256(_PDF_BYTES).hexdigest(),
                    "fetched_at": "2026-04-01T00:00:00+00:00",
                }
            }
        )
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers.get("If-None-Match") == _ETAG
        assert request.headers.get("If-Modified-Since") == _LAST_MODIFIED
        return httpx.Response(304)

    async with _client(handler) as client:
        [r] = await fetch_pdfs(
            [_make_source()],
            client=client,
            data_dir=data_dir,
            cache_path=cache_path,
        )
    assert r.changed is False
    assert r.local_path == target
    assert r.sha256 == hashlib.sha256(_PDF_BYTES).hexdigest()


async def test_fetch_pdfs_force_refetch_ignores_cache(tmp_path: Path) -> None:
    data_dir = tmp_path / "strategy_docs"
    cache_path = tmp_path / "cache" / "sources_state.json"
    data_dir.mkdir(parents=True)
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "sample": {
                    "resolved_url": "https://example.com/sample.pdf",
                    "etag": _ETAG,
                    "last_modified": _LAST_MODIFIED,
                    "sha256": "old",
                    "fetched_at": "2026-04-01T00:00:00+00:00",
                }
            }
        )
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=_PDF_BYTES)

    async with _client(handler) as client:
        [r] = await fetch_pdfs(
            [_make_source()],
            client=client,
            data_dir=data_dir,
            cache_path=cache_path,
            force_refetch=True,
        )
    assert "If-None-Match" not in requests[0].headers
    assert "If-Modified-Since" not in requests[0].headers
    assert r.changed is True


async def test_fetch_pdfs_propagates_404(tmp_path: Path) -> None:
    data_dir = tmp_path / "strategy_docs"
    cache_path = tmp_path / "cache" / "sources_state.json"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    async with _client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_pdfs(
                [_make_source()],
                client=client,
                data_dir=data_dir,
                cache_path=cache_path,
            )
