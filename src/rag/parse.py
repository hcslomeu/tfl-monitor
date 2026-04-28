"""Parse a PDF via Docling and emit chunks with retrieval metadata.

Docling 2.x's :class:`docling.chunking.HybridChunker` segments by
document hierarchy and merges sibling chunks under a token cap, which
matches the retrieval granularity we want for ``text-embedding-3-small``.
The Docling imports are deferred to the call site so unit tests can
inject lightweight fakes without paying the model-download cost.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol, cast

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """A retrievable chunk of a parsed PDF, with citation metadata."""

    doc_id: str
    doc_title: str
    resolved_url: str
    chunk_index: int = Field(ge=0)
    section_title: str = ""
    page_start: int | None = None
    page_end: int | None = None
    text: str = Field(min_length=1)


class _DoclingConverter(Protocol):
    def convert(self, source: str) -> Any: ...


class _DoclingChunker(Protocol):
    def chunk(self, document: Any) -> Iterable[Any]: ...


def parse_pdf(
    *,
    doc_id: str,
    doc_title: str,
    resolved_url: str,
    pdf_path: Path,
    converter: _DoclingConverter | None = None,
    chunker: _DoclingChunker | None = None,
) -> list[Chunk]:
    """Parse ``pdf_path`` and return a list of :class:`Chunk`.

    Args:
        doc_id: Stable doc identifier (also the Pinecone namespace).
        doc_title: Human-readable title carried into chunk metadata.
        resolved_url: URL the PDF was downloaded from.
        pdf_path: Local path to the PDF on disk.
        converter: Optional injection point for tests; defaults to a
            Docling :class:`DocumentConverter`.
        chunker: Optional injection point for tests; defaults to
            :class:`docling.chunking.HybridChunker` with library defaults.
    """
    converter = converter or _default_converter()
    chunker = chunker or _default_chunker()
    document = converter.convert(str(pdf_path)).document
    chunks: list[Chunk] = []
    for index, raw in enumerate(chunker.chunk(document)):
        text = _chunk_text(raw)
        if not text.strip():
            continue
        section_title, page_start, page_end = _extract_meta(raw)
        chunks.append(
            Chunk(
                doc_id=doc_id,
                doc_title=doc_title,
                resolved_url=resolved_url,
                chunk_index=index,
                section_title=section_title,
                page_start=page_start,
                page_end=page_end,
                text=text,
            )
        )
    return chunks


def _default_converter() -> _DoclingConverter:
    from docling.document_converter import DocumentConverter

    return cast(_DoclingConverter, DocumentConverter())


def _default_chunker() -> _DoclingChunker:
    from docling.chunking import HybridChunker  # type: ignore[attr-defined]

    return cast(_DoclingChunker, HybridChunker())


def _chunk_text(raw: Any) -> str:
    text = getattr(raw, "text", None)
    if isinstance(text, str):
        return text
    return str(raw)


def _extract_meta(raw: Any) -> tuple[str, int | None, int | None]:
    meta = getattr(raw, "meta", None)
    headings = getattr(meta, "headings", None) or []
    section_title = ""
    for heading in headings:
        if isinstance(heading, str) and heading.strip():
            section_title = heading
            break
    pages: list[int] = []
    for item in getattr(meta, "doc_items", None) or []:
        for prov in getattr(item, "prov", None) or []:
            page_no = getattr(prov, "page_no", None)
            if isinstance(page_no, int):
                pages.append(page_no)
    page_start = min(pages) if pages else None
    page_end = max(pages) if pages else None
    return section_title, page_start, page_end
