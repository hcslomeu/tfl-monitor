"""Unit tests for :mod:`rag.sources`."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from rag.sources import (
    PdfSource,
    PdfSourceResolutionError,
    load_sources,
    resolve_pdf_urls,
    write_sources,
)

_LANDING_HTML = """
<!doctype html>
<html><body>
  <a href="/cdn/static/cms/documents/2026-business-plan-acc.pdf">Read</a>
  <a href="/sites/default/files/some-other.pdf">Other</a>
</body></html>
"""


def _build_source() -> PdfSource:
    return PdfSource(
        name="TfL Business Plan",
        doc_id="tfl_business_plan",
        landing_url="https://tfl.gov.uk/corporate/publications-and-reports/business-plan",
        discovery_regex=r"business-plan.*\.pdf$",
    )


def _client_with_response(*, status: int, text: str) -> httpx.AsyncClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status, text=text)

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


async def test_resolve_pdf_urls_picks_first_match() -> None:
    source = _build_source()
    async with _client_with_response(status=200, text=_LANDING_HTML) as client:
        [resolved] = await resolve_pdf_urls([source], client=client)
    assert (
        str(resolved.resolved_url)
        == "https://tfl.gov.uk/cdn/static/cms/documents/2026-business-plan-acc.pdf"
    )
    assert resolved.doc_id == source.doc_id


async def test_resolve_pdf_urls_resolves_relative_href() -> None:
    """Hrefs relative to the landing URL must be made absolute."""
    source = _build_source()
    async with _client_with_response(
        status=200,
        text='<a href="/cdn/static/cms/documents/2026-business-plan-acc.pdf">Read</a>',
    ) as client:
        [resolved] = await resolve_pdf_urls([source], client=client)
    assert str(resolved.resolved_url).startswith("https://tfl.gov.uk/")


async def test_resolve_pdf_urls_raises_when_no_link_matches() -> None:
    source = _build_source()
    async with _client_with_response(
        status=200, text='<a href="/some-unrelated-doc.pdf">x</a>'
    ) as client:
        with pytest.raises(PdfSourceResolutionError) as excinfo:
            await resolve_pdf_urls([source], client=client)
    msg = str(excinfo.value)
    assert "business-plan" in msg
    assert "tfl.gov.uk" in msg


def test_load_and_write_sources_roundtrip(tmp_path: Path) -> None:
    source = PdfSource(
        name="Test Source",
        doc_id="test_source",
        landing_url="https://example.com/landing",
        discovery_regex=r"test.*\.pdf$",
        resolved_url="https://example.com/test.pdf",
    )
    target = tmp_path / "sources.json"
    write_sources(target, [source])
    [reloaded] = load_sources(target)
    assert reloaded.doc_id == source.doc_id
    assert str(reloaded.resolved_url) == str(source.resolved_url)


def test_committed_sources_json_is_valid() -> None:
    """The shipped ``src/rag/sources.json`` must parse into PdfSource."""
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "src" / "rag" / "sources.json"
    sources = load_sources(path)
    assert {s.doc_id for s in sources} == {
        "tfl_business_plan",
        "mts_2018",
        "tfl_annual_report",
    }
    for s in sources:
        assert s.resolved_url is not None
        assert json.dumps(s.discovery_regex)  # always serialisable
