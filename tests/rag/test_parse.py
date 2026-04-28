"""Unit tests for :mod:`rag.parse`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rag.parse import Chunk, parse_pdf


@dataclass
class _FakeProv:
    page_no: int


@dataclass
class _FakeDocItem:
    prov: list[_FakeProv]


@dataclass
class _FakeMeta:
    headings: list[str] = field(default_factory=list)
    doc_items: list[_FakeDocItem] = field(default_factory=list)


@dataclass
class _FakeChunk:
    text: str
    meta: _FakeMeta


@dataclass
class _FakeConvertResult:
    document: object


class _FakeConverter:
    def __init__(self, document: object) -> None:
        self._document = document
        self.calls: list[str] = []

    def convert(self, source: str) -> _FakeConvertResult:
        self.calls.append(source)
        return _FakeConvertResult(document=self._document)


class _FakeChunker:
    def __init__(self, chunks: list[_FakeChunk]) -> None:
        self._chunks = chunks

    def chunk(self, _document: object) -> list[_FakeChunk]:
        return self._chunks


def _build_fake_chunk(
    text: str,
    *,
    headings: list[str] | None = None,
    pages: list[int] | None = None,
) -> _FakeChunk:
    return _FakeChunk(
        text=text,
        meta=_FakeMeta(
            headings=list(headings or []),
            doc_items=[_FakeDocItem(prov=[_FakeProv(page_no=p) for p in (pages or [])])],
        ),
    )


def test_parse_pdf_emits_one_chunk_per_section(tmp_path: Path) -> None:
    pdf_path = tmp_path / "fake.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    converter = _FakeConverter(document=object())
    chunker = _FakeChunker(
        [
            _build_fake_chunk("Intro paragraph.", headings=["Introduction"], pages=[1, 2]),
            _build_fake_chunk(
                "Methodology details.",
                headings=["Methods", "Subsection"],
                pages=[3],
            ),
        ]
    )

    chunks = parse_pdf(
        doc_id="doc",
        doc_title="Test Doc",
        resolved_url="https://example.com/doc.pdf",
        pdf_path=pdf_path,
        converter=converter,
        chunker=chunker,
    )

    assert [c.section_title for c in chunks] == ["Introduction", "Methods"]
    assert [c.page_start for c in chunks] == [1, 3]
    assert [c.page_end for c in chunks] == [2, 3]
    assert [c.chunk_index for c in chunks] == [0, 1]
    assert all(isinstance(c, Chunk) for c in chunks)
    assert converter.calls == [str(pdf_path)]


def test_parse_pdf_skips_empty_text_chunks(tmp_path: Path) -> None:
    pdf_path = tmp_path / "fake.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    converter = _FakeConverter(document=object())
    chunker = _FakeChunker(
        [
            _build_fake_chunk("Real content"),
            _build_fake_chunk("   "),  # whitespace-only
            _build_fake_chunk("More content"),
        ]
    )

    chunks = parse_pdf(
        doc_id="doc",
        doc_title="Test Doc",
        resolved_url="https://example.com/doc.pdf",
        pdf_path=pdf_path,
        converter=converter,
        chunker=chunker,
    )

    assert [c.text for c in chunks] == ["Real content", "More content"]
    # chunk_index reflects the chunker's enumeration so retrieval citation
    # remains meaningful even when the parser skips whitespace.
    assert [c.chunk_index for c in chunks] == [0, 2]
