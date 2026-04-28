"""Unit tests for the LlamaIndex RAG retriever."""

from __future__ import annotations

import pytest

from api.agent.rag import NAMESPACES, retrieve

from .conftest import FakeRetriever, make_node


@pytest.mark.asyncio
async def test_fan_out_when_doc_id_is_none() -> None:
    """``doc_id=None`` queries every namespace once."""
    retrievers = {
        ns: FakeRetriever(nodes=[make_node(doc_id=ns, score=0.5 + idx / 10)])
        for idx, ns in enumerate(NAMESPACES)
    }

    snippets = await retrieve(retrievers, query="forecasts", doc_id=None, top_k=10)

    for ns in NAMESPACES:
        assert retrievers[ns].queries == ["forecasts"]
    assert {s.doc_id for s in snippets} == set(NAMESPACES)


@pytest.mark.asyncio
async def test_single_namespace_when_doc_id_set() -> None:
    """When ``doc_id`` is set, only that namespace is queried."""
    retrievers = {ns: FakeRetriever(nodes=[make_node(doc_id=ns)]) for ns in NAMESPACES}

    snippets = await retrieve(retrievers, query="capex", doc_id="mts_2018", top_k=10)

    assert retrievers["mts_2018"].queries == ["capex"]
    assert retrievers["tfl_business_plan"].queries == []
    assert retrievers["tfl_annual_report"].queries == []
    assert {s.doc_id for s in snippets} == {"mts_2018"}


@pytest.mark.asyncio
async def test_page_sentinel_maps_to_none() -> None:
    """The ``-1`` sentinel from TM-D4 surfaces as ``None``."""
    retrievers = {
        "tfl_business_plan": FakeRetriever(nodes=[make_node(page_start=None, page_end=None)])
    }
    snippets = await retrieve(retrievers, query="x", doc_id="tfl_business_plan", top_k=5)
    assert snippets[0].page_start is None
    assert snippets[0].page_end is None


@pytest.mark.asyncio
async def test_results_sorted_by_score_desc_and_capped() -> None:
    """``top_k`` slices after a global score-descending sort."""
    retrievers = {
        "tfl_business_plan": FakeRetriever(
            nodes=[
                make_node(doc_id="tfl_business_plan", text="low", score=0.1),
                make_node(doc_id="tfl_business_plan", text="high", score=0.9),
            ]
        ),
        "mts_2018": FakeRetriever(nodes=[make_node(doc_id="mts_2018", text="mid", score=0.5)]),
        "tfl_annual_report": FakeRetriever(
            nodes=[make_node(doc_id="tfl_annual_report", text="top", score=0.95)]
        ),
    }

    snippets = await retrieve(retrievers, query="q", doc_id=None, top_k=2)

    assert [s.text for s in snippets] == ["top", "high"]
    assert all(snippets[i].score >= snippets[i + 1].score for i in range(len(snippets) - 1))
