"""Unit tests for :mod:`rag.parse`."""

from __future__ import annotations

from pathlib import Path

from rag.parse import (
    Chunk,
    PageText,
    _default_extractor,
    _default_splitter,
    _LlamaIndexSplitter,
    _PyMuPdfExtractor,
    parse_pdf,
)


class _FakeExtractor:
    """Returns canned pages and records the path it was asked to extract."""

    def __init__(self, pages: list[PageText]) -> None:
        self._pages = pages
        self.calls: list[Path] = []

    def extract(self, pdf_path: Path) -> list[PageText]:
        self.calls.append(pdf_path)
        return self._pages


class _DelimiterSplitter:
    """Deterministic splitter: splits on ``|`` so tests control the pieces."""

    def split_text(self, text: str) -> list[str]:
        return text.split("|")


class _RecordingInnerSplitter:
    def __init__(self, pieces: list[str]) -> None:
        self._pieces = pieces
        self.calls: list[str] = []

    def split_text(self, text: str) -> list[str]:
        self.calls.append(text)
        return self._pieces


def test_parse_pdf_emits_chunk_per_split_with_page_numbers(tmp_path: Path) -> None:
    pdf_path = tmp_path / "fake.pdf"
    extractor = _FakeExtractor(
        [
            PageText(page_no=1, text="intro one|intro two"),
            PageText(page_no=2, text="methods"),
        ]
    )

    chunks = parse_pdf(
        doc_id="doc",
        doc_title="Test Doc",
        resolved_url="https://example.com/doc.pdf",
        pdf_path=pdf_path,
        extractor=extractor,
        splitter=_DelimiterSplitter(),
    )

    assert [c.text for c in chunks] == ["intro one", "intro two", "methods"]
    assert [c.page_start for c in chunks] == [1, 1, 2]
    assert [c.page_end for c in chunks] == [1, 1, 2]
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert all(isinstance(c, Chunk) for c in chunks)
    assert all(c.doc_id == "doc" and c.doc_title == "Test Doc" for c in chunks)
    assert extractor.calls == [pdf_path]


def test_parse_pdf_skips_whitespace_only_pieces(tmp_path: Path) -> None:
    pdf_path = tmp_path / "fake.pdf"
    extractor = _FakeExtractor([PageText(page_no=1, text="real|   |more")])

    chunks = parse_pdf(
        doc_id="doc",
        doc_title="Test Doc",
        resolved_url="https://example.com/doc.pdf",
        pdf_path=pdf_path,
        extractor=extractor,
        splitter=_DelimiterSplitter(),
    )

    assert [c.text for c in chunks] == ["real", "more"]
    # chunk_index stays contiguous over emitted chunks so vector ids are dense.
    assert [c.chunk_index for c in chunks] == [0, 1]


def test_default_extractor_is_pymupdf() -> None:
    assert isinstance(_default_extractor(), _PyMuPdfExtractor)


def test_default_splitter_returns_text_splitter() -> None:
    """The default splitter must expose ``split_text`` over real input.

    ``parse_pdf`` lets tests inject a fake splitter, so the real
    ``_default_splitter`` wiring is otherwise uncovered — a refactor could
    return an object without the Protocol method and only fail at ingest time.
    """
    splitter = _default_splitter()
    pieces = splitter.split_text("A short sentence. Another short sentence.")
    assert isinstance(pieces, list)
    assert all(isinstance(p, str) for p in pieces)


def test_llamaindex_splitter_delegates_to_inner() -> None:
    inner = _RecordingInnerSplitter(["a", "b"])
    adapter = _LlamaIndexSplitter(inner)

    result = adapter.split_text("a b")

    assert result == ["a", "b"]
    assert inner.calls == ["a b"]
