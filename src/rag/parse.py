"""Parse a PDF into retrievable chunks with citation metadata.

Text extraction uses PyMuPDF (lightweight, no torch) and chunking uses
LlamaIndex's :class:`SentenceSplitter`. Both heavy imports are deferred to
the call site so unit tests can inject lightweight fakes. The TfL corpus is
born-digital prose, so the layout/OCR models Docling loaded are unnecessary
here — see ADR 013.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

# Chunking granularity for SentenceSplitter. ~512 tokens keeps each chunk
# well under the Titan v2 input cap while staying large enough to retain
# paragraph-level context; the overlap preserves continuity across splits.
DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 64


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


class PageText(BaseModel):
    """Extracted plain text for a single 1-indexed PDF page."""

    page_no: int = Field(ge=1)
    text: str


class _PdfExtractor(Protocol):
    def extract(self, pdf_path: Path) -> list[PageText]: ...


class _TextSplitter(Protocol):
    def split_text(self, text: str) -> list[str]: ...


def parse_pdf(
    *,
    doc_id: str,
    doc_title: str,
    resolved_url: str,
    pdf_path: Path,
    extractor: _PdfExtractor | None = None,
    splitter: _TextSplitter | None = None,
) -> list[Chunk]:
    """Parse ``pdf_path`` and return a list of :class:`Chunk`.

    Each page's text is split into sentence-aware chunks; every chunk carries
    its source page number so the retriever can cite a page. ``chunk_index``
    is a contiguous, deterministic counter over emitted chunks, which keeps
    the per-chunk vector ids stable across re-ingestion runs.

    Args:
        doc_id: Stable doc identifier.
        doc_title: Human-readable title carried into chunk metadata.
        resolved_url: URL the PDF was downloaded from.
        pdf_path: Local path to the PDF on disk.
        extractor: Optional injection point for tests; defaults to a
            PyMuPDF-backed extractor.
        splitter: Optional injection point for tests; defaults to a
            LlamaIndex :class:`SentenceSplitter`.
    """
    extractor = extractor or _default_extractor()
    splitter = splitter or _default_splitter()
    chunks: list[Chunk] = []
    index = 0
    for page in extractor.extract(pdf_path):
        for piece in splitter.split_text(page.text):
            text = piece.strip()
            if not text:
                continue
            chunks.append(
                Chunk(
                    doc_id=doc_id,
                    doc_title=doc_title,
                    resolved_url=resolved_url,
                    chunk_index=index,
                    section_title="",
                    page_start=page.page_no,
                    page_end=page.page_no,
                    text=text,
                )
            )
            index += 1
    return chunks


def _default_extractor() -> _PdfExtractor:
    return _PyMuPdfExtractor()


class _PyMuPdfExtractor:
    """PyMuPDF-backed extractor emitting one :class:`PageText` per page."""

    def extract(self, pdf_path: Path) -> list[PageText]:
        import pymupdf  # noqa: PLC0415 - deferred so unit tests skip the import

        pages: list[PageText] = []
        # pymupdf.open aliases the untyped Document constructor; the result is
        # iterated as Any, which is fine for the page-text extraction below.
        with pymupdf.open(str(pdf_path)) as document:  # type: ignore[no-untyped-call]
            for number, page in enumerate(document, start=1):
                # Postgres text/varchar reject null bytes; strip them before
                # the extracted text reaches the pgvector store.
                text = page.get_text("text").replace("\x00", "")
                pages.append(PageText(page_no=number, text=text))
        return pages


def _default_splitter() -> _TextSplitter:
    from llama_index.core.node_parser import SentenceSplitter  # noqa: PLC0415

    return _LlamaIndexSplitter(
        SentenceSplitter(chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP)
    )


class _LlamaIndexSplitter:
    """Adapter exposing LlamaIndex's splitter through the ``_TextSplitter`` Protocol."""

    def __init__(self, splitter: Any) -> None:
        self._splitter = splitter

    def split_text(self, text: str) -> list[str]:
        return list(self._splitter.split_text(text))
