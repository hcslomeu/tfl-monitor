"""Top-level RAG ingestion orchestrator.

Pipeline: ``resolve URLs?`` → ``conditional fetch`` → ``parse`` →
``embed`` → ``upsert``. Run via ``uv run python -m rag.ingest``.

CLI flags:

- ``--refresh-urls`` re-resolves the direct-PDF URL for every source
  and rewrites ``src/rag/sources.json``.
- ``--force-refetch`` ignores cached ``ETag`` / ``Last-Modified`` and
  re-downloads unconditionally.
- ``--dry-run`` runs everything except the Pinecone upsert.

Fail-loud on missing ``OPENAI_API_KEY`` / ``PINECONE_API_KEY``: the
process exits with code 2.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
import logfire
from openai import AsyncOpenAI

from rag.config import RagSettings, load_settings
from rag.embed import embed_texts
from rag.fetch import (
    DEFAULT_CACHE_PATH,
    DEFAULT_DATA_DIR,
    FetchResult,
    fetch_pdfs,
    load_cache,
)
from rag.parse import Chunk, parse_pdf
from rag.sources import load_sources, resolve_pdf_urls, write_sources
from rag.upsert import ensure_index, upsert_chunks

__all__ = ["main", "run_ingestion"]

DEFAULT_SOURCES_PATH = Path("src/rag/sources.json")
RAG_SERVICE_NAME = "tfl-monitor-rag-ingestion"


def configure_logfire() -> None:
    """Configure Logfire for the ingestion entrypoint."""
    logfire.configure(
        service_name=RAG_SERVICE_NAME,
        service_version=os.getenv("APP_VERSION", "0.0.1"),
        environment=os.getenv("ENVIRONMENT", "local"),
        send_to_logfire="if-token-present",
    )
    logfire.instrument_httpx()


async def _amain(
    *,
    force_refetch: bool,
    dry_run: bool,
    refresh_urls: bool,
    sources_path: Path = DEFAULT_SOURCES_PATH,
    data_dir: Path = DEFAULT_DATA_DIR,
    cache_path: Path = DEFAULT_CACHE_PATH,
    pinecone_factory: Any = None,
    openai_factory: Any = None,
    httpx_factory: Any = None,
    docling_converter: Any = None,
    docling_chunker: Any = None,
) -> int:
    configure_logfire()
    settings = load_settings()
    sources = load_sources(sources_path)

    # Snapshot previous resolved URLs *before* the fetch step rewrites the
    # cache so we can detect URL rollover for namespace cleanup later.
    previous_urls = {
        doc_id: entry.get("resolved_url", "") for doc_id, entry in load_cache(cache_path).items()
    }

    httpx_factory = httpx_factory or _default_httpx_factory
    async with httpx_factory() as client:
        if refresh_urls:
            sources = await resolve_pdf_urls(sources, client=client)
            write_sources(sources_path, sources)
        results = await fetch_pdfs(
            sources,
            client=client,
            data_dir=data_dir,
            cache_path=cache_path,
            force_refetch=force_refetch,
        )

    openai_client = (openai_factory or _default_openai_factory)(settings)
    pinecone_client = (pinecone_factory or _default_pinecone_factory)(settings)
    ensure_index(
        pinecone_client,
        name=settings.pinecone_index,
        cloud=settings.pinecone_cloud,
        region=settings.pinecone_region,
    )
    index = pinecone_client.Index(settings.pinecone_index)

    total_upserted = 0
    for result in results:
        upserted = await _ingest_one(
            result=result,
            previous_urls=previous_urls,
            settings=settings,
            openai_client=openai_client,
            index=index,
            dry_run=dry_run,
            docling_converter=docling_converter,
            docling_chunker=docling_chunker,
        )
        total_upserted += upserted

    logfire.info(
        "rag.ingest.done",
        total_upserted=total_upserted,
        dry_run=dry_run,
    )
    return total_upserted


async def _ingest_one(
    *,
    result: FetchResult,
    previous_urls: dict[str, str],
    settings: RagSettings,
    openai_client: Any,
    index: Any,
    dry_run: bool,
    docling_converter: Any,
    docling_chunker: Any,
) -> int:
    with logfire.span(
        "rag.ingest.cycle",
        doc_id=result.source.doc_id,
        changed=result.changed,
        dry_run=dry_run,
    ):
        chunks: list[Chunk] = parse_pdf(
            doc_id=result.source.doc_id,
            doc_title=result.source.name,
            resolved_url=str(result.source.resolved_url),
            pdf_path=result.local_path,
            converter=docling_converter,
            chunker=docling_chunker,
        )
        if not chunks:
            logfire.warn(
                "rag.ingest.empty_chunks",
                doc_id=result.source.doc_id,
            )
            return 0
        vectors = await embed_texts(
            [c.text for c in chunks],
            client=openai_client,
            model=settings.embedding_model,
        )
        if dry_run:
            logfire.info(
                "rag.ingest.dry_run",
                doc_id=result.source.doc_id,
                chunks=len(chunks),
                vectors=len(vectors),
            )
            return 0
        previous_url = previous_urls.get(result.source.doc_id)
        rollover = bool(previous_url and previous_url != str(result.source.resolved_url))
        return upsert_chunks(
            index=index,
            chunks=chunks,
            vectors=vectors,
            namespace=result.source.doc_id,
            delete_namespace_first=rollover,
        )


def _default_pinecone_factory(settings: RagSettings) -> Any:
    from pinecone import Pinecone

    return Pinecone(api_key=settings.pinecone_api_key.get_secret_value())


def _default_openai_factory(settings: RagSettings) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())


def _default_httpx_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=60.0)


def run_ingestion(
    *,
    force_refetch: bool = False,
    dry_run: bool = False,
    refresh_urls: bool = False,
) -> int:
    """Synchronous entrypoint used by ``python -m rag.ingest``."""
    return asyncio.run(
        _amain(
            force_refetch=force_refetch,
            dry_run=dry_run,
            refresh_urls=refresh_urls,
        )
    )


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint for ``python -m rag.ingest``."""
    parser = argparse.ArgumentParser(
        prog="rag.ingest",
        description="Ingest TfL strategy PDFs into Pinecone via Docling.",
    )
    parser.add_argument(
        "--force-refetch",
        action="store_true",
        help="Ignore cached ETag/Last-Modified and re-download.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the Pinecone upsert step.",
    )
    parser.add_argument(
        "--refresh-urls",
        action="store_true",
        help="Re-resolve direct-PDF URLs from landing pages.",
    )
    args = parser.parse_args(argv)
    run_ingestion(
        force_refetch=args.force_refetch,
        dry_run=args.dry_run,
        refresh_urls=args.refresh_urls,
    )


if __name__ == "__main__":
    main()
