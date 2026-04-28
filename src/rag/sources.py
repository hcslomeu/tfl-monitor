"""Resolve the direct-PDF URL of each TfL strategy landing page.

The three landing pages (``business-plan``, ``mayors-transport-strategy-2018``,
``annual-report``) host the canonical PDFs but rotate the link target by
year (Business Plan and Annual Report) or keep it stable (MTS 2018).
``resolve_pdf_urls`` scrapes each landing page once and picks the first
``<a href="...">`` whose URL matches a per-source allowlist regex.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, Field, HttpUrl

PDF_LINK_HREF_PATTERN = re.compile(r"""href=["']([^"']+\.pdf(?:\?[^"']*)?)["']""", re.IGNORECASE)


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
    """Load the committed ``src/rag/sources.json`` file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [PdfSource.model_validate(entry) for entry in raw]


def write_sources(path: Path, sources: list[PdfSource]) -> None:
    """Write ``sources`` back to disk as JSON, sorted by ``doc_id``."""
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

    Args:
        sources: Sources to refresh.
        client: Shared async HTTP client.

    Returns:
        New list with ``resolved_url`` populated from the landing page.

    Raises:
        PdfSourceResolutionError: When a landing page returns no link
            matching the source's ``discovery_regex``.
    """
    return [await _resolve_one(source, client=client) for source in sources]


async def _resolve_one(
    source: PdfSource,
    *,
    client: httpx.AsyncClient,
) -> PdfSource:
    response = await client.get(str(source.landing_url), follow_redirects=True)
    response.raise_for_status()
    pattern = re.compile(source.discovery_regex, re.IGNORECASE)
    base_url = str(response.url)
    for match in PDF_LINK_HREF_PATTERN.finditer(response.text):
        href = match.group(1)
        if pattern.search(href):
            absolute = urljoin(base_url, href)
            return source.model_copy(update={"resolved_url": absolute})
    raise PdfSourceResolutionError(
        f"No PDF link matching {source.discovery_regex!r} found on {source.landing_url}"
    )
