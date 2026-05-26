"""Unit tests for the pgvector-backed LlamaIndex RAG retriever."""

from __future__ import annotations

import pytest

from api.agent.rag import DOC_IDS, retrieve

from .conftest import FakeIndex, make_node


@pytest.mark.asyncio
async def test_no_filter_when_doc_id_is_none() -> None:
    """``doc_id=None`` queries the whole corpus (no metadata filter)."""
    index = FakeIndex(nodes=[make_node(doc_id=ns, score=0.5) for ns in DOC_IDS])

    snippets = await retrieve(index, query="forecasts", doc_id=None, top_k=10)

    assert index.captured["filters"] is None
    assert {s.doc_id for s in snippets} == set(DOC_IDS)
    assert index.last_retriever is not None
    assert index.last_retriever.queries == ["forecasts"]


@pytest.mark.asyncio
async def test_metadata_filter_when_doc_id_set() -> None:
    """A ``doc_id`` becomes a single ``doc_id`` equality metadata filter."""
    index = FakeIndex(nodes=[make_node(doc_id=ns) for ns in DOC_IDS])

    snippets = await retrieve(index, query="capex", doc_id="vision_zero", top_k=10)

    metadata_filter = index.captured["filters"].filters[0]
    assert metadata_filter.key == "doc_id"
    assert metadata_filter.value == "vision_zero"
    assert {s.doc_id for s in snippets} == {"vision_zero"}


@pytest.mark.asyncio
async def test_page_sentinel_maps_to_none() -> None:
    """The ``-1`` page sentinel surfaces as ``None``."""
    index = FakeIndex(nodes=[make_node(page_start=None, page_end=None)])

    snippets = await retrieve(index, query="x", doc_id="business_plan_2026", top_k=5)

    assert snippets[0].page_start is None
    assert snippets[0].page_end is None


@pytest.mark.asyncio
async def test_results_sorted_by_score_desc_and_capped() -> None:
    """``top_k`` slices after a score-descending sort."""
    index = FakeIndex(
        nodes=[
            make_node(text="low", score=0.1),
            make_node(text="top", score=0.95),
            make_node(text="mid", score=0.5),
        ]
    )

    snippets = await retrieve(index, query="q", doc_id=None, top_k=2)

    assert [s.text for s in snippets] == ["top", "mid"]
    assert all(snippets[i].score >= snippets[i + 1].score for i in range(len(snippets) - 1))


@pytest.mark.asyncio
async def test_retrieve_returns_empty_on_store_failure() -> None:
    """A pgvector failure degrades gracefully to no snippets."""
    index = FakeIndex(nodes=[make_node()], raise_on_retriever=True)

    snippets = await retrieve(index, query="q", doc_id=None, top_k=5)

    assert snippets == []
