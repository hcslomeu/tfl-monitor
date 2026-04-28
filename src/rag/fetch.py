"""Conditional download of resolved TfL PDFs to ``data/strategy_docs/``.

Each fetch sends ``If-None-Match`` and ``If-Modified-Since`` from the
sidecar cache (``data/cache/sources_state.json``). HTTP 304 short-circuits
without writing the file; HTTP 200 writes the bytes and refreshes the
cache. HTTP 4xx/5xx propagates — we never silently fall back to a stale
cache when the upstream URL has gone bad.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import logfire
from pydantic import BaseModel

from rag.sources import PdfSource

DEFAULT_DATA_DIR = Path("data/strategy_docs")
DEFAULT_CACHE_PATH = Path("data/cache/sources_state.json")


class FetchResult(BaseModel):
    """Outcome of fetching a single :class:`PdfSource`."""

    source: PdfSource
    local_path: Path
    changed: bool
    sha256: str
    etag: str | None
    last_modified: str | None


def load_cache(path: Path) -> dict[str, dict[str, str]]:
    """Read the sidecar cache; missing file yields an empty mapping."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, dict[str, str]] = {}
    for doc_id, entry in raw.items():
        if isinstance(doc_id, str) and isinstance(entry, dict):
            cleaned[doc_id] = {str(key): str(value) for key, value in entry.items()}
    return cleaned


def write_cache(path: Path, state: dict[str, dict[str, str]]) -> None:
    """Persist the sidecar cache as JSON, parents created on demand."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


async def fetch_pdfs(
    sources: list[PdfSource],
    *,
    client: httpx.AsyncClient,
    data_dir: Path = DEFAULT_DATA_DIR,
    cache_path: Path = DEFAULT_CACHE_PATH,
    force_refetch: bool = False,
) -> list[FetchResult]:
    """Conditionally download every source to ``data_dir``.

    Args:
        sources: Sources whose ``resolved_url`` is already populated.
        client: Shared async HTTP client.
        data_dir: Where to write the downloaded PDFs.
        cache_path: Sidecar cache location.
        force_refetch: When ``True`` ignores cached headers.

    Returns:
        One :class:`FetchResult` per source. ``changed=True`` means the
        bytes were rewritten (HTTP 200); ``False`` means the cached
        copy is still authoritative (HTTP 304).
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    state = load_cache(cache_path)
    results: list[FetchResult] = []
    for source in sources:
        result = await _fetch_one(
            source,
            client=client,
            data_dir=data_dir,
            cached=state.get(source.doc_id, {}),
            force_refetch=force_refetch,
        )
        results.append(result)
    state.update(
        {
            r.source.doc_id: {
                "resolved_url": str(r.source.resolved_url),
                "etag": r.etag or "",
                "last_modified": r.last_modified or "",
                "sha256": r.sha256,
                "fetched_at": datetime.now(UTC).isoformat(),
            }
            for r in results
        }
    )
    write_cache(cache_path, state)
    return results


async def _fetch_one(
    source: PdfSource,
    *,
    client: httpx.AsyncClient,
    data_dir: Path,
    cached: dict[str, str],
    force_refetch: bool,
) -> FetchResult:
    if source.resolved_url is None:
        raise RuntimeError(f"Source {source.doc_id!r} has no resolved_url")

    target = data_dir / f"{source.doc_id}.pdf"
    headers: dict[str, str] = {}
    if not force_refetch and cached:
        cached_etag = cached.get("etag", "")
        cached_lm = cached.get("last_modified", "")
        if cached_etag:
            headers["If-None-Match"] = cached_etag
        if cached_lm:
            headers["If-Modified-Since"] = cached_lm

    with logfire.span(
        "rag.fetch",
        doc_id=source.doc_id,
        url=str(source.resolved_url),
        force_refetch=force_refetch,
    ):
        response = await client.get(
            str(source.resolved_url),
            headers=headers,
            follow_redirects=True,
        )
        if response.status_code == 304:
            if target.exists():
                sha = cached.get("sha256") or _sha256_of(target)
                return FetchResult(
                    source=source,
                    local_path=target,
                    changed=False,
                    sha256=sha,
                    etag=cached.get("etag") or None,
                    last_modified=cached.get("last_modified") or None,
                )
            # Cache headers said "unchanged" but the local PDF is gone
            # (manual cleanup, broken volume, lost mount). The 304
            # response has no body so writing it would yield a 0-byte
            # file; re-issue the request without conditional headers.
            logfire.warn(
                "rag.fetch.cache_invalidated_local_file_missing",
                doc_id=source.doc_id,
                target=str(target),
            )
            response = await client.get(
                str(source.resolved_url),
                follow_redirects=True,
            )
        response.raise_for_status()
        target.write_bytes(response.content)
        sha = _sha256_of(target)
        return FetchResult(
            source=source,
            local_path=target,
            changed=True,
            sha256=sha,
            etag=response.headers.get("ETag") or None,
            last_modified=response.headers.get("Last-Modified") or None,
        )


def _sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()
