"""Top-level RAG ingestion orchestrator.

Pipeline: ``resolve URLs?`` → ``conditional fetch`` → ``parse`` →
``embed`` → ``upsert``. Run via ``uv run python -m rag.ingest``.

CLI flags:

- ``--refresh-urls`` re-resolves the direct-PDF URL for every source
  and rewrites ``src/rag/sources.json``.
- ``--force-refetch`` ignores cached ``ETag`` / ``Last-Modified`` and
  re-downloads unconditionally.
- ``--dry-run`` fetches and parses but skips embedding and the
  pgvector upsert.

Embeddings use Bedrock Titan v2 and vectors land in pgvector; both read
AWS credentials and the Postgres DSN from the environment, so the
process exits ``code=2`` only when the settings themselves are malformed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import logfire

from common.sampling import build_sampling_options
from rag.config import load_settings
from rag.fetch import (
    DEFAULT_CACHE_PATH,
    DEFAULT_DATA_DIR,
    FetchResult,
    fetch_pdfs,
)
from rag.parse import Chunk, parse_pdf
from rag.sources import load_sources, resolve_pdf_urls, write_sources
from rag.upsert import upsert_chunks
from rag.vectorstore import build_embedding, build_vector_store

__all__ = ["main", "run_ingestion"]

DEFAULT_SOURCES_PATH = Path("src/rag/sources.json")
RAG_SERVICE_NAME = "tfl-monitor-rag-ingestion"

_DEFAULT_SAMPLE_RATE = 0.5


def configure_logfire() -> None:
    """Configure Logfire for the ingestion entrypoint."""
    logfire.configure(
        service_name=RAG_SERVICE_NAME,
        service_version=os.getenv("APP_VERSION", "0.0.1"),
        environment=os.getenv("ENVIRONMENT", "local"),
        send_to_logfire="if-token-present",
        sampling=build_sampling_options(_DEFAULT_SAMPLE_RATE),
    )


async def _amain(
    *,
    force_refetch: bool,
    dry_run: bool,
    refresh_urls: bool,
    sources_path: Path = DEFAULT_SOURCES_PATH,
    data_dir: Path = DEFAULT_DATA_DIR,
    cache_path: Path = DEFAULT_CACHE_PATH,
    embedding_factory: Any = None,
    vector_store_factory: Any = None,
    httpx_factory: Any = None,
    docling_converter: Any = None,
    docling_chunker: Any = None,
) -> int:
    configure_logfire()
    settings = load_settings()
    sources = load_sources(sources_path)

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

    embed_model = (embedding_factory or build_embedding)(settings)
    vector_store = None if dry_run else (vector_store_factory or build_vector_store)(settings)

    total_upserted = 0
    failures: list[tuple[str, str]] = []
    for result in results:
        try:
            upserted = await _ingest_one(
                result=result,
                embed_model=embed_model,
                vector_store=vector_store,
                dry_run=dry_run,
                docling_converter=docling_converter,
                docling_chunker=docling_chunker,
            )
        except Exception as exc:  # noqa: BLE001 - aggregate per-doc failures
            logfire.error(
                "rag.ingest.cycle_failed",
                doc_id=result.source.doc_id,
                error=repr(exc),
            )
            failures.append((result.source.doc_id, repr(exc)))
            continue
        total_upserted += upserted

    logfire.info(
        "rag.ingest.done",
        total_upserted=total_upserted,
        dry_run=dry_run,
        failures=len(failures),
    )
    if failures:
        details = "; ".join(f"{doc_id}: {err}" for doc_id, err in failures)
        sys.stderr.write(f"RAG ingestion finished with {len(failures)} failure(s): {details}\n")
        raise SystemExit(1)
    return total_upserted


async def _ingest_one(
    *,
    result: FetchResult,
    embed_model: Any,
    vector_store: Any,
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
        if not result.changed:
            # HTTP 304 cache hit -> nothing new to embed/upsert. The
            # delete-then-insert path would only burn Bedrock calls and
            # rewrite identical rows. Honour the idempotent-by-cost
            # contract documented in the README.
            logfire.info("rag.ingest.skipped_unchanged", doc_id=result.source.doc_id)
            return 0
        chunks: list[Chunk] = parse_pdf(
            doc_id=result.source.doc_id,
            doc_title=result.source.name,
            resolved_url=str(result.source.resolved_url),
            pdf_path=result.local_path,
            converter=docling_converter,
            chunker=docling_chunker,
        )
        if not chunks:
            logfire.warn("rag.ingest.empty_chunks", doc_id=result.source.doc_id)
            return 0
        if dry_run:
            logfire.info(
                "rag.ingest.dry_run",
                doc_id=result.source.doc_id,
                chunks=len(chunks),
            )
            return 0
        return upsert_chunks(
            vector_store=vector_store,
            embed_model=embed_model,
            chunks=chunks,
            doc_id=result.source.doc_id,
            delete_first=True,
        )


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
        description="Ingest TfL strategy PDFs into pgvector via Docling + Bedrock.",
    )
    parser.add_argument(
        "--force-refetch",
        action="store_true",
        help="Ignore cached ETag/Last-Modified and re-download every PDF.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run fetch + parse but skip embedding and the pgvector upsert step.",
    )
    parser.add_argument(
        "--refresh-urls",
        action="store_true",
        help=(
            "Re-scrape every landing page and rewrite the resolved direct-PDF "
            "URL in src/rag/sources.json. Use this when TfL rolls a stem "
            "(e.g. 2026-business-plan -> 2027-business-plan). The subsequent "
            "download is still conditional via ETag, so unchanged PDFs are 304'd."
        ),
    )
    args = parser.parse_args(argv)
    run_ingestion(
        force_refetch=args.force_refetch,
        dry_run=args.dry_run,
        refresh_urls=args.refresh_urls,
    )


if __name__ == "__main__":
    main()
