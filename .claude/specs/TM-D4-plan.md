# TM-D4 — Implementation plan (Phase 2)

Source: `TM-D4-research.md` (2026-04-28).

All ten open questions from the research file (Q1-Q10) resolved as the
recommended defaults. No author callout was raised in the research; the
plan proceeds directly.

## Summary

Land a self-contained `src/rag/` package that:

1. Resolves the current direct-PDF URL on each of the three TfL strategy
   landing pages (Business Plan, Mayor's Transport Strategy 2018, Annual
   Report) by scraping the landing HTML for an allowlisted PDF link.
2. Conditionally downloads each PDF using cached `ETag` /
   `Last-Modified` to `data/strategy_docs/<doc_id>.pdf`.
3. Parses each PDF through Docling 2.x and chunks via
   `docling.chunking.HybridChunker` into ~512-token chunks with
   section/heading/page metadata.
4. Embeds chunks via OpenAI `text-embedding-3-small` (1536 dim, async,
   batches of 100, retry on 429).
5. Upserts vectors into Pinecone serverless index `tfl-strategy-docs`,
   one namespace per `doc_id`, with stable id =
   `sha256(f"{resolved_url}::{chunk_index}").hexdigest()`. Idempotent
   on repeat runs; deletes the namespace before upsert when
   `resolved_url` rolled over.
6. Runs as `uv run python -m rag.ingest` with `--force-refetch` and
   `--dry-run` flags. Fails loud with exit code 2 when
   `PINECONE_API_KEY` or `OPENAI_API_KEY` is missing.

No edits to `contracts/`. No new runtime dependency
(`docling`, `pinecone`, `openai`, `httpx`, `pydantic-settings`,
`logfire` already in `pyproject.toml`). LlamaIndex is intentionally
not used.

## Execution mode

- **Author of change:** single-track WP — execute serially in the main
  workspace (only `src/rag/`, `tests/rag/`, `data/` (gitignored),
  `.gitignore`, and `README.md` touched).
- **Branch:** `feature/TM-D4-rag-ingestion`.
- **PR title:** `feat(rag): TM-D4 Docling → Pinecone RAG ingestion with
  auto PDF fetch (TM-17)`.
- **PR body:** `Closes TM-17`; lists deliverables, the conditional-GET
  semantics, the per-doc namespace cleanup-on-rollover semantics, the
  CLI flags, and the failure model.

## What we're NOT doing

- No retrieval logic (TM-D5 builds the LangGraph `search_tfl_docs`
  tool).
- No reranking, no hybrid (BM25 + vector) — TM-D5 layers that on top
  of the index this WP populates.
- No Airflow DAG to schedule ingestion (TM-A2). `cron`-style refresh
  is the manual `uv run python -m rag.ingest` until then.
- No edits to `contracts/schemas/*`, `contracts/sql/*`,
  `contracts/openapi.yaml` — frozen.
- No `LlamaIndex` dependency wiring. Docling alone covers parse +
  chunk for this WP.
- No new TypeScript or web changes. Track is `D-api-agent`, scope is
  `src/rag/` + `tests/rag/`.
- No Pinecone metadata-filter delete (free-tier serverless does not
  support it). Use `delete(delete_all=True, namespace=doc_id)` for
  rollover cleanup.
- No new env var beyond `OPENAI_API_KEY`, `PINECONE_API_KEY`,
  `PINECONE_INDEX`, `EMBEDDING_MODEL`. `LOGFIRE_TOKEN` is reused if
  set; otherwise Logfire stays in console mode (`send_to_logfire="if-token-present"`).
- No `Makefile` target — RAG ingestion is run on-demand by the author
  via `uv run python -m rag.ingest`. Adding a target would push the
  Makefile from 10 to 11 with no recurring orchestration value
  (CLAUDE.md §"Principle #1" rule 2 keeps the Makefile small).

## Sub-phases

### Phase 3.1 — Package skeleton + config

#### `src/rag/__init__.py` (new)

Re-export the top-level orchestrator and the settings loader so tests
and `python -m rag.ingest` import cleanly.

```python
"""RAG ingestion package: TfL strategy PDFs → Docling → Pinecone."""

from rag.config import RagSettings, load_settings
from rag.ingest import run_ingestion

__all__ = ["RagSettings", "load_settings", "run_ingestion"]
```

#### `src/rag/config.py` (new)

Single `Settings(BaseSettings)` class — five fields, well under the
≥15 trigger for nested settings (CLAUDE.md §"Principle #1" rule 5).

```python
"""Pydantic settings for RAG ingestion."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PINECONE_INDEX = "tfl-strategy-docs"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
DEFAULT_PINECONE_CLOUD = "aws"
DEFAULT_PINECONE_REGION = "us-east-1"


class RagSettings(BaseSettings):
    """RAG ingestion configuration loaded from the process environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: SecretStr
    pinecone_api_key: SecretStr
    pinecone_index: str = DEFAULT_PINECONE_INDEX
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    pinecone_cloud: str = DEFAULT_PINECONE_CLOUD
    pinecone_region: str = DEFAULT_PINECONE_REGION


def load_settings() -> RagSettings:
    """Load and validate ``RagSettings`` from the environment.

    Raises ``SystemExit(2)`` with a readable message when required
    secrets are missing — fail loud per the briefing's hard rule.
    """
    try:
        return RagSettings()  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001 - boundary
        msg = f"RAG settings missing or invalid: {exc!s}"
        raise SystemExit(msg) from None
```

`SecretStr` ensures Logfire and pytest reprs never expose key
contents (CLAUDE.md §"Security-first").

### Phase 3.2 — `src/rag/sources.py` and `src/rag/sources.json`

#### `src/rag/sources.py` (new)

```python
"""Resolve the direct-PDF URL of each TfL strategy landing page."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Self
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, Field, HttpUrl

PDF_LINK_HREF_PATTERN = re.compile(
    r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', re.IGNORECASE
)


class PdfSource(BaseModel):
    """A TfL strategy PDF and its discovery + cached state."""

    name: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    landing_url: HttpUrl
    discovery_regex: str = Field(min_length=1)
    resolved_url: HttpUrl | None = None
    etag: str | None = None
    last_modified: str | None = None
    sha256: str | None = None


class PdfSourceResolutionError(RuntimeError):
    """Raised when a landing page exposes no matching PDF link."""


def load_sources(path: Path) -> list[PdfSource]:
    """Load ``src/rag/sources.json`` into a list of ``PdfSource``."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [PdfSource.model_validate(entry) for entry in raw]


def write_sources(path: Path, sources: list[PdfSource]) -> None:
    """Write ``sources`` back to disk, sorted by ``doc_id``."""
    serialised = [
        {
            "name": s.name,
            "doc_id": s.doc_id,
            "landing_url": str(s.landing_url),
            "discovery_regex": s.discovery_regex,
            "resolved_url": str(s.resolved_url) if s.resolved_url else None,
        }
        for s in sorted(sources, key=lambda s: s.doc_id)
    ]
    path.write_text(json.dumps(serialised, indent=2) + "\n", encoding="utf-8")


async def resolve_pdf_urls(
    sources: list[PdfSource],
    *,
    client: httpx.AsyncClient,
) -> list[PdfSource]:
    """Re-resolve every source's ``resolved_url`` from its landing page.

    Returns a new list with ``resolved_url`` updated. Raises
    ``PdfSourceResolutionError`` when a landing page has no PDF link
    matching the source's ``discovery_regex``.
    """
    return [await _resolve_one(s, client=client) for s in sources]


async def _resolve_one(
    source: PdfSource, *, client: httpx.AsyncClient
) -> PdfSource:
    response = await client.get(str(source.landing_url), follow_redirects=True)
    response.raise_for_status()
    pattern = re.compile(source.discovery_regex, re.IGNORECASE)
    for match in PDF_LINK_HREF_PATTERN.finditer(response.text):
        href = match.group(1)
        if pattern.search(href):
            absolute = urljoin(str(response.url), href)
            return source.model_copy(update={"resolved_url": absolute})
    raise PdfSourceResolutionError(
        f"No PDF link matching {source.discovery_regex!r} found on "
        f"{source.landing_url}"
    )
```

#### `src/rag/sources.json` (new, committed)

```json
[
  {
    "name": "TfL Business Plan",
    "doc_id": "tfl_business_plan",
    "landing_url": "https://tfl.gov.uk/corporate/publications-and-reports/business-plan",
    "discovery_regex": "business-plan.*\\.pdf$",
    "resolved_url": "https://content.tfl.gov.uk/2026-business-plan-acc.pdf"
  },
  {
    "name": "Mayor's Transport Strategy",
    "doc_id": "mts_2018",
    "landing_url": "https://www.london.gov.uk/programmes-strategies/transport/our-vision-transport/mayors-transport-strategy-2018",
    "discovery_regex": "mayors-transport-strategy-2018.*\\.pdf$",
    "resolved_url": "https://www.london.gov.uk/sites/default/files/mayors-transport-strategy-2018.pdf"
  },
  {
    "name": "TfL Annual Report",
    "doc_id": "tfl_annual_report",
    "landing_url": "https://tfl.gov.uk/corporate/publications-and-reports/annual-report",
    "discovery_regex": "annual-report-and-statement-of-accounts.*\\.pdf$",
    "resolved_url": "https://content.tfl.gov.uk/tfl-annual-report-and-statement-of-accounts-2024-25.pdf"
  }
]
```

### Phase 3.3 — `src/rag/fetch.py` (conditional GET + cache)

```python
"""Conditional download of resolved TfL PDFs to ``data/strategy_docs/``."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx
import logfire

from rag.sources import PdfSource

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("data/strategy_docs")
DEFAULT_CACHE_PATH = Path("data/cache/sources_state.json")


class FetchResult:
    """Outcome of fetching a single PdfSource."""

    def __init__(
        self,
        *,
        source: PdfSource,
        local_path: Path,
        changed: bool,
        sha256: str,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        self.source = source
        self.local_path = local_path
        self.changed = changed
        self.sha256 = sha256
        self.etag = etag
        self.last_modified = last_modified


def load_cache(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_cache(path: Path, state: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


async def fetch_pdfs(
    sources: list[PdfSource],
    *,
    client: httpx.AsyncClient,
    data_dir: Path = DEFAULT_DATA_DIR,
    cache_path: Path = DEFAULT_CACHE_PATH,
    force_refetch: bool = False,
) -> list[FetchResult]:
    """Conditionally download each ``PdfSource`` to disk.

    Returns one ``FetchResult`` per source. ``changed`` is ``True`` for
    a real download (HTTP 200) and ``False`` for HTTP 304 / cache hit.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    state = load_cache(cache_path)
    results = [
        await _fetch_one(
            source, client=client, data_dir=data_dir,
            cached=state.get(source.doc_id, {}),
            force_refetch=force_refetch,
        )
        for source in sources
    ]
    state.update({
        r.source.doc_id: {
            "resolved_url": str(r.source.resolved_url),
            "etag": r.etag or "",
            "last_modified": r.last_modified or "",
            "sha256": r.sha256,
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        for r in results
    })
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
        msg = f"Source {source.doc_id!r} has no resolved_url"
        raise RuntimeError(msg)
    target = data_dir / f"{source.doc_id}.pdf"
    headers: dict[str, str] = {}
    if not force_refetch and cached:
        if "etag" in cached and cached["etag"]:
            headers["If-None-Match"] = cached["etag"]
        if "last_modified" in cached and cached["last_modified"]:
            headers["If-Modified-Since"] = cached["last_modified"]
    with logfire.span(
        "rag.fetch", doc_id=source.doc_id,
        url=str(source.resolved_url), force_refetch=force_refetch,
    ):
        response = await client.get(
            str(source.resolved_url), headers=headers,
            follow_redirects=True,
        )
        if response.status_code == 304 and target.exists():
            sha = cached.get("sha256") or _sha256_of(target)
            return FetchResult(
                source=source, local_path=target, changed=False,
                sha256=sha,
                etag=cached.get("etag") or None,
                last_modified=cached.get("last_modified") or None,
            )
        response.raise_for_status()
        target.write_bytes(response.content)
        sha = _sha256_of(target)
        return FetchResult(
            source=source, local_path=target, changed=True,
            sha256=sha,
            etag=response.headers.get("ETag") or None,
            last_modified=response.headers.get("Last-Modified") or None,
        )


def _sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()
```

### Phase 3.4 — `src/rag/parse.py` (Docling + chunking)

```python
"""Parse a PDF via Docling and emit chunks with retrieval metadata."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_MAX_TOKENS = 512


class Chunk(BaseModel):
    """Chunk of a parsed PDF with retrieval metadata."""

    doc_id: str
    doc_title: str
    resolved_url: str
    chunk_index: int = Field(ge=0)
    section_title: str = ""
    page_start: int | None = None
    page_end: int | None = None
    text: str = Field(min_length=1)


def parse_pdf(
    *, doc_id: str, doc_title: str, resolved_url: str,
    pdf_path: Path, max_tokens: int = DEFAULT_CHUNK_MAX_TOKENS,
    converter: Any | None = None, chunker: Any | None = None,
) -> list[Chunk]:
    """Parse ``pdf_path`` and return ``Chunk`` objects.

    ``converter`` and ``chunker`` exist only for unit-test injection;
    in production they default to ``DocumentConverter()`` and
    ``HybridChunker(max_tokens=max_tokens, merge_peers=True)``.
    """
    converter = converter or _default_converter()
    chunker = chunker or _default_chunker(max_tokens=max_tokens)
    document = converter.convert(str(pdf_path)).document
    chunks: list[Chunk] = []
    for index, raw in enumerate(chunker.chunk(document)):
        section_title, page_start, page_end = _extract_meta(raw)
        text = _chunk_text(raw)
        if not text.strip():
            continue
        chunks.append(Chunk(
            doc_id=doc_id, doc_title=doc_title, resolved_url=resolved_url,
            chunk_index=index, section_title=section_title,
            page_start=page_start, page_end=page_end, text=text,
        ))
    return chunks


def _default_converter() -> Any:
    from docling.document_converter import DocumentConverter
    return DocumentConverter()


def _default_chunker(*, max_tokens: int) -> Any:
    from docling.chunking import HybridChunker
    return HybridChunker(max_tokens=max_tokens, merge_peers=True)


def _chunk_text(raw: Any) -> str:
    text = getattr(raw, "text", None)
    if isinstance(text, str):
        return text
    return str(raw)


def _extract_meta(raw: Any) -> tuple[str, int | None, int | None]:
    meta = getattr(raw, "meta", None)
    headings: Iterable[str] = getattr(meta, "headings", None) or []
    section_title = next(iter(headings), "")
    pages: list[int] = []
    for item in getattr(meta, "doc_items", None) or []:
        for prov in getattr(item, "prov", None) or []:
            page_no = getattr(prov, "page_no", None)
            if isinstance(page_no, int):
                pages.append(page_no)
    page_start = min(pages) if pages else None
    page_end = max(pages) if pages else None
    return section_title, page_start, page_end
```

The lazy imports of Docling keep test runs that mock the converter
free of the heavy Docling import. Type is `Any` for the injected
fakes — Docling's runtime objects are duck-typed via the helpers.

### Phase 3.5 — `src/rag/embed.py` (async OpenAI)

```python
"""Async OpenAI embeddings with batching and 429-aware retry."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

import logfire
from openai import (
    APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError,
)

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_ATTEMPTS = 5
_BASE_BACKOFF_SECONDS = 0.5
_MAX_BACKOFF_SECONDS = 10.0


def _exponential_backoff(attempt: int) -> float:
    delay: float = _BASE_BACKOFF_SECONDS * (2**attempt)
    return min(delay, _MAX_BACKOFF_SECONDS)


async def embed_texts(
    texts: Sequence[str],
    *,
    client: AsyncOpenAI,
    model: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> list[list[float]]:
    """Embed ``texts`` in batches; return one vector per input."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        with logfire.span(
            "rag.embed", model=model, n_inputs=len(batch),
            batch_index=start // batch_size,
        ):
            response = await _embed_batch_with_retry(
                batch, client=client, model=model,
                max_attempts=max_attempts,
            )
        vectors.extend([item.embedding for item in response.data])
    return vectors


async def _embed_batch_with_retry(
    batch: list[str], *, client: AsyncOpenAI, model: str,
    max_attempts: int,
) -> Any:
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await client.embeddings.create(model=model, input=batch)
        except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
            last_exc = exc
            if attempt == max_attempts - 1:
                break
            await asyncio.sleep(_exponential_backoff(attempt))
    raise RuntimeError(
        f"OpenAI embed failed after {max_attempts} attempts: {last_exc!r}"
    )
```

### Phase 3.6 — `src/rag/upsert.py` (Pinecone)

```python
"""Pinecone upsert: create index if absent, namespace-per-doc, idempotent."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from typing import Any, Protocol

import logfire

from rag.config import (
    DEFAULT_PINECONE_CLOUD, DEFAULT_PINECONE_REGION, EMBEDDING_DIMENSIONS,
)
from rag.parse import Chunk

logger = logging.getLogger(__name__)

UPSERT_BATCH_SIZE = 100


class _PineconeIndex(Protocol):
    def upsert(self, *, vectors: list[dict[str, Any]],
               namespace: str) -> Any: ...
    def delete(self, *, delete_all: bool, namespace: str) -> Any: ...


class _PineconeClient(Protocol):
    def list_indexes(self) -> Any: ...
    def create_index(self, *, name: str, dimension: int, metric: str,
                     spec: Any) -> Any: ...
    def Index(self, name: str) -> _PineconeIndex: ...


def vector_id(resolved_url: str, chunk_index: int) -> str:
    """Stable per-chunk id used as the Pinecone vector id."""
    digest = hashlib.sha256(
        f"{resolved_url}::{chunk_index}".encode("utf-8")
    ).hexdigest()
    return digest


def ensure_index(
    client: _PineconeClient, *, name: str,
    cloud: str = DEFAULT_PINECONE_CLOUD,
    region: str = DEFAULT_PINECONE_REGION,
) -> None:
    """Create the index if missing; idempotent."""
    from pinecone import ServerlessSpec  # lazy import keeps unit tests fake-only

    existing = {entry["name"] for entry in client.list_indexes()}
    if name in existing:
        return
    client.create_index(
        name=name, dimension=EMBEDDING_DIMENSIONS, metric="cosine",
        spec=ServerlessSpec(cloud=cloud, region=region),
    )


def upsert_chunks(
    *, index: _PineconeIndex, chunks: Iterable[Chunk],
    vectors: list[list[float]], namespace: str,
    delete_namespace_first: bool,
) -> int:
    """Upsert one batch per ``UPSERT_BATCH_SIZE`` vectors. Returns count."""
    if delete_namespace_first:
        with logfire.span(
            "rag.upsert.delete_namespace", namespace=namespace,
        ):
            index.delete(delete_all=True, namespace=namespace)
    payload = [
        {
            "id": vector_id(chunk.resolved_url, chunk.chunk_index),
            "values": vec,
            "metadata": {
                "doc_id": chunk.doc_id,
                "doc_title": chunk.doc_title,
                "resolved_url": chunk.resolved_url,
                "chunk_index": chunk.chunk_index,
                "section_title": chunk.section_title,
                "page_start": chunk.page_start if chunk.page_start is not None else -1,
                "page_end": chunk.page_end if chunk.page_end is not None else -1,
                "text": chunk.text,
            },
        }
        for chunk, vec in zip(chunks, vectors, strict=True)
    ]
    upserted = 0
    for start in range(0, len(payload), UPSERT_BATCH_SIZE):
        batch = payload[start : start + UPSERT_BATCH_SIZE]
        with logfire.span(
            "rag.upsert", namespace=namespace, n_vectors=len(batch),
            batch_index=start // UPSERT_BATCH_SIZE,
        ):
            index.upsert(vectors=batch, namespace=namespace)
        upserted += len(batch)
    return upserted
```

`page_start`/`page_end` are coerced to `-1` when missing because
Pinecone metadata cannot hold `null`. The retriever in TM-D5 will
treat `-1` as "unknown".

### Phase 3.7 — `src/rag/ingest.py` (orchestrator + CLI)

```python
"""Top-level RAG ingestion: resolve → fetch → parse → embed → upsert."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import httpx
import logfire
from openai import AsyncOpenAI

from rag.config import RagSettings, load_settings
from rag.embed import embed_texts
from rag.fetch import (
    DEFAULT_CACHE_PATH, DEFAULT_DATA_DIR, fetch_pdfs, load_cache,
)
from rag.parse import Chunk, parse_pdf
from rag.sources import PdfSource, load_sources, resolve_pdf_urls, write_sources
from rag.upsert import ensure_index, upsert_chunks

logger = logging.getLogger(__name__)
SOURCES_PATH = Path("src/rag/sources.json")
RAG_SERVICE_NAME = "tfl-monitor-rag-ingestion"


def configure_logfire() -> None:
    import os
    logfire.configure(
        service_name=RAG_SERVICE_NAME,
        service_version=os.getenv("APP_VERSION", "0.0.1"),
        environment=os.getenv("ENVIRONMENT", "local"),
        send_to_logfire="if-token-present",
    )
    logfire.instrument_httpx()


async def _amain(*, force_refetch: bool, dry_run: bool,
                 refresh_urls: bool) -> None:
    configure_logfire()
    settings = load_settings()
    sources = load_sources(SOURCES_PATH)

    async with httpx.AsyncClient(timeout=60.0) as client:
        if refresh_urls:
            sources = await resolve_pdf_urls(sources, client=client)
            write_sources(SOURCES_PATH, sources)

        results = await fetch_pdfs(
            sources, client=client, force_refetch=force_refetch,
        )

    cache = load_cache(DEFAULT_CACHE_PATH)
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
    pinecone_client = _build_pinecone_client(settings)
    ensure_index(
        pinecone_client, name=settings.pinecone_index,
        cloud=settings.pinecone_cloud, region=settings.pinecone_region,
    )
    index = pinecone_client.Index(settings.pinecone_index)

    total_upserted = 0
    for result in results:
        with logfire.span(
            "rag.ingest.cycle", doc_id=result.source.doc_id,
            changed=result.changed, dry_run=dry_run,
        ):
            chunks = parse_pdf(
                doc_id=result.source.doc_id,
                doc_title=result.source.name,
                resolved_url=str(result.source.resolved_url),
                pdf_path=result.local_path,
            )
            if not chunks:
                logfire.warn(
                    "rag.ingest.empty_chunks",
                    doc_id=result.source.doc_id,
                )
                continue
            vectors = await embed_texts(
                [c.text for c in chunks],
                client=openai_client,
                model=settings.embedding_model,
            )
            if dry_run:
                logfire.info(
                    "rag.ingest.dry_run", doc_id=result.source.doc_id,
                    chunks=len(chunks), vectors=len(vectors),
                )
                continue
            previous_url = cache.get(result.source.doc_id, {}).get(
                "resolved_url"
            )
            rollover = bool(
                previous_url
                and previous_url != str(result.source.resolved_url)
            )
            total_upserted += upsert_chunks(
                index=index, chunks=chunks, vectors=vectors,
                namespace=result.source.doc_id,
                delete_namespace_first=rollover,
            )
    logfire.info("rag.ingest.done", total_upserted=total_upserted,
                 dry_run=dry_run)


def _build_pinecone_client(settings: RagSettings) -> object:
    from pinecone import Pinecone  # lazy import for unit-test fakes
    return Pinecone(api_key=settings.pinecone_api_key.get_secret_value())


def run_ingestion(*, force_refetch: bool = False, dry_run: bool = False,
                  refresh_urls: bool = False) -> None:
    """Synchronous entrypoint used by ``python -m rag.ingest``."""
    asyncio.run(_amain(
        force_refetch=force_refetch, dry_run=dry_run,
        refresh_urls=refresh_urls,
    ))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest TfL strategy PDFs into Pinecone via Docling."
    )
    parser.add_argument("--force-refetch", action="store_true",
                        help="Ignore cached ETag/Last-Modified.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip the Pinecone upsert step.")
    parser.add_argument("--refresh-urls", action="store_true",
                        help="Re-resolve direct-PDF URLs from landing pages.")
    args = parser.parse_args()
    run_ingestion(
        force_refetch=args.force_refetch, dry_run=args.dry_run,
        refresh_urls=args.refresh_urls,
    )


if __name__ == "__main__":
    main()
```

### Phase 3.8 — Tests under `tests/rag/`

Layout:

```
tests/rag/
├── __init__.py
├── conftest.py
├── test_sources.py
├── test_fetch.py
├── test_parse.py
├── test_embed.py
├── test_upsert.py
└── test_ingest.py
```

`conftest.py` sets the bare-minimum env vars so `RagSettings()`
constructs in unit tests:

```python
import os
import pytest

@pytest.fixture(autouse=True)
def _rag_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PINECONE_API_KEY", "pcsk-test")
```

#### `test_sources.py`

1. `test_resolve_pdf_urls_picks_first_match` — `httpx.MockTransport`
   serves a stub HTML with two PDF links; resolver returns the first
   matching the `discovery_regex`.
2. `test_resolve_pdf_urls_resolves_relative_href` — landing page
   uses `<a href="/cdn/static/cms/documents/2026-business-plan-acc.pdf">`;
   resolver returns the absolute URL.
3. `test_resolve_pdf_urls_raises_when_no_link_matches` — HTML has no
   PDF link; assert `PdfSourceResolutionError` carries the regex and
   landing URL in the message.
4. `test_load_and_write_sources_roundtrip` — `load_sources`
   then `write_sources` to a temp path; assert file round-trips.

#### `test_fetch.py`

1. `test_fetch_pdfs_writes_file_and_cache_on_200` — `httpx.MockTransport`
   returns 200 + `ETag` + `Last-Modified`; assert file written, cache
   updated, `changed=True`, `sha256` is the digest of the bytes.
2. `test_fetch_pdfs_skips_on_304` — pre-seed cache with last
   ETag and an existing file; transport returns 304; assert no file
   write, `changed=False`, `sha256` reused from cache.
3. `test_fetch_pdfs_force_refetch_ignores_cache` — pre-seed cache;
   transport returns 200 again; assert `If-None-Match` header *not*
   sent on the request.
4. `test_fetch_pdfs_propagates_404` — transport returns 404; assert
   `httpx.HTTPStatusError` propagates (we never silently fall back).

#### `test_parse.py`

1. `test_parse_pdf_emits_one_chunk_per_section` — fake
   `DocumentConverter` and fake `HybridChunker` (callables returning a
   prefab list of objects mimicking the Docling shape with `text`,
   `meta.headings`, `meta.doc_items[*].prov[*].page_no`); assert
   `Chunk` count, `section_title`, `page_start`, `page_end`,
   `chunk_index`.
2. `test_parse_pdf_skips_empty_text_chunks` — fake produces a chunk
   with whitespace-only text; assert it is dropped; `chunk_index`
   gap is preserved (i.e. indices reflect the chunker's order).

#### `test_embed.py`

1. `test_embed_texts_batches_at_100` — fake `AsyncOpenAI` records
   each call's `input` length; assert two calls for 150 inputs (100,
   50).
2. `test_embed_texts_retries_on_rate_limit` — fake raises
   `RateLimitError` once then succeeds; assert two calls and the
   final vectors match.
3. `test_embed_texts_raises_after_exhaustion` — fake raises
   `RateLimitError` `max_attempts=2` times; assert `RuntimeError`
   wraps the last exception.

#### `test_upsert.py`

1. `test_vector_id_is_stable` — same `(resolved_url, chunk_index)`
   yields same digest; different inputs differ.
2. `test_ensure_index_skips_when_present` — fake client lists the
   index; assert no `create_index` call.
3. `test_ensure_index_creates_when_missing` — fake client lists `[]`;
   assert one `create_index` call with `dimension=1536`,
   `metric="cosine"`.
4. `test_upsert_chunks_deletes_namespace_when_rollover` — pass
   `delete_namespace_first=True`; assert `delete(delete_all=True,
   namespace=...)` precedes the upsert.
5. `test_upsert_chunks_skips_delete_when_not_rollover` — pass
   `delete_namespace_first=False`; assert no `delete` call.
6. `test_upsert_chunks_metadata_shape` — assert metadata dict has
   `doc_id`, `doc_title`, `resolved_url`, `chunk_index`,
   `section_title`, `page_start`, `page_end`, `text`; missing pages
   coerced to `-1`.
7. `test_upsert_chunks_batches_at_100` — 250 chunks; assert three
   `upsert` calls (100, 100, 50).

#### `test_ingest.py`

1. `test_run_ingestion_end_to_end_with_fakes` — monkeypatch every
   external client (`httpx.AsyncClient`, `AsyncOpenAI`, Pinecone
   client, Docling converter+chunker) to deterministic fakes; run
   `run_ingestion()`; assert one upsert per source, namespace per
   `doc_id`, total vector count.
2. `test_run_ingestion_dry_run_skips_upsert` — same wiring with
   `dry_run=True`; assert no `index.upsert` call.
3. `test_run_ingestion_rollover_triggers_namespace_delete` —
   pre-seed `data/cache/sources_state.json` with a *different*
   `resolved_url` for one doc; assert `delete(delete_all=True,
   namespace=that_doc_id)` is called.
4. `test_run_ingestion_missing_pinecone_key_exits_2` —
   monkeypatch `PINECONE_API_KEY` to `""`; assert `SystemExit(2)`
   (or `SystemExit` with non-zero exit code).

### Phase 3.9 — `.gitignore`, README, `.env.example`

`.gitignore` — append:

```
data/strategy_docs/*.pdf
data/cache/
```

`.env.example` — `PINECONE_INDEX` already present; append a comment
documenting the new RAG-specific defaults under the existing
`# Vector DB` block:

```
# RAG ingestion (TM-D4)
# PINECONE_INDEX overrides the default "tfl-strategy-docs"
# EMBEDDING_MODEL overrides the default "text-embedding-3-small"
EMBEDDING_MODEL=text-embedding-3-small
```

(Do not add `PINECONE_INDEX` again; already declared.)

`README.md` — new "RAG ingestion" subsection under "Local
development", placed after the existing local-dev block:

```markdown
### RAG ingestion (TM-D4)

```bash
# Run once to populate Pinecone
uv run python -m rag.ingest

# Re-resolve direct-PDF URLs from the TfL/GLA landing pages
uv run python -m rag.ingest --refresh-urls

# Bypass the ETag cache
uv run python -m rag.ingest --force-refetch

# Parse + embed only; do not upsert (sizing + smoke check)
uv run python -m rag.ingest --dry-run
```

PDFs are fetched conditionally (`If-None-Match` / `If-Modified-Since`)
to `data/strategy_docs/`. The first run downloads ~60 MB total. Set
`PINECONE_API_KEY` and `OPENAI_API_KEY` in `.env`. Index name and
embedding model can be overridden via `PINECONE_INDEX` and
`EMBEDDING_MODEL`.
```

### Phase 3.10 — Verification gate

Per napkin §Execution#5:

```bash
uv run task lint                           # ruff + format-check + mypy strict
uv run task test                           # default suite
uv run bandit -r src --severity-level high # HIGH only
make check                                 # lint + test + dbt-parse + TS lint + TS build
```

All four must exit 0. `make check` already includes `dbt-parse` and
the TS chain — no edits to those targets are required.

A manual smoke against real Pinecone is documented but optional:

```bash
PINECONE_API_KEY=... OPENAI_API_KEY=... \
  uv run python -m rag.ingest --dry-run
```

(`--dry-run` so the smoke does not pollute the user's index.)

### Phase 3.11 — PR

- Branch: `feature/TM-D4-rag-ingestion`
- PR title:
  `feat(rag): TM-D4 Docling → Pinecone RAG ingestion with auto PDF fetch (TM-17)`
- PR body bullets:
  - landing-page → resolved-PDF URL discovery via committed
    `discovery_regex` per source (`src/rag/sources.json`);
  - conditional GET (`If-None-Match` / `If-Modified-Since`) into
    `data/strategy_docs/` with sha256 + ETag in `data/cache/sources_state.json`;
  - Docling 2.x parse + `HybridChunker(max_tokens=512,
    merge_peers=True)`;
  - OpenAI `text-embedding-3-small` async batching (100/req, 5
    attempts on `RateLimitError`);
  - Pinecone serverless `tfl-strategy-docs` (cosine, 1536), one
    namespace per `doc_id`, stable id =
    `sha256("{resolved_url}::{chunk_index}").hexdigest()`,
    delete-namespace-on-rollover idempotency;
  - CLI flags `--refresh-urls`, `--force-refetch`, `--dry-run`;
  - fail-loud on missing `PINECONE_API_KEY` / `OPENAI_API_KEY`
    (`SystemExit(2)`);
  - `.gitignore` extends with `data/strategy_docs/*.pdf` +
    `data/cache/`;
  - README "RAG ingestion" section.
- **Out of scope** — TM-D5 retrieval, TM-A2 Airflow DAG.
- **Closes TM-17.**

## Success criteria

- [ ] `src/rag/__init__.py`, `config.py`, `sources.py`, `fetch.py`,
  `parse.py`, `embed.py`, `upsert.py`, `ingest.py` created and
  importable.
- [ ] `src/rag/sources.json` committed with the three TfL sources and
  validated by `PdfSource.model_validate`.
- [ ] `data/strategy_docs/`, `data/cache/` excluded from git.
- [ ] `python -m rag.ingest --dry-run` succeeds end-to-end against
  real Pinecone (manual smoke, documented; not required in CI).
- [ ] Conditional GET path verified (re-running after first run
  returns `changed=False` for unchanged docs).
- [ ] All seven unit-test files under `tests/rag/` cover the
  scenarios listed in Phase 3.8.
- [ ] `uv run task lint` passes (ruff + mypy strict on new modules).
- [ ] `uv run task test` passes.
- [ ] `uv run bandit -r src --severity-level high` reports zero
  findings.
- [ ] `make check` passes end-to-end.
- [ ] README "RAG ingestion" section landed.
- [ ] `.env.example` extended with `EMBEDDING_MODEL` (PINECONE_INDEX
  already present).
- [ ] `PROGRESS.md` TM-D4 row updated to ✅ with completion date.
- [ ] PR opened on branch `feature/TM-D4-rag-ingestion` with
  `Closes TM-17` in body.
- [ ] Linear TM-17 transitions to Done on merge.

## Open questions (resolved during planning)

All ten Q1-Q10 from `TM-D4-research.md` resolved as the recommended
defaults. No author callout was raised in the research file; if real
PDF parsing surfaces a Docling oddity (e.g. `meta.headings` shape
differs from the doc), Phase 3 will course-correct and STOP per
CLAUDE.md §"Phase approach": "Expected: X. Found: Y. How should I
proceed?"

## References

- `.claude/specs/TM-D4-research.md` — surface map and open questions.
- `CLAUDE.md` — §"Tech stack", §"Principle #1", §"Pydantic usage",
  §"Observability architecture", §"Security-first".
- `AGENTS.md` — §1 track inventory.
- `pyproject.toml` — pins `docling`, `pinecone`, `openai`,
  `pydantic-settings`, `httpx`, `logfire`.
- `src/ingestion/tfl_client/retry.py` — pattern for the OpenAI retry
  loop.
- `src/ingestion/observability.py` — pattern for the RAG Logfire
  helper (kept inline in `ingest.py` here because it is the sole
  ingestion-style entrypoint in the package).
- Pinecone Python client v5 docs (consulted via context7 at
  implementation time).
- Docling 2.x docs — `docling.chunking.HybridChunker`,
  `docling.document_converter.DocumentConverter`.
