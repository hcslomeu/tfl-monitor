"""LlamaIndex retrieval over the Pinecone tfl-strategy-docs index.

One retriever per ``doc_id`` namespace. ``retrieve`` fans out across
all namespaces when no ``doc_id`` is supplied; otherwise it queries a
single namespace. Page sentinel ``-1`` (TM-D4 upsert convention) maps
to ``None`` so the LLM never sees a sentinel page number.
"""

from __future__ import annotations

import asyncio
from typing import Any

from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import BaseRetriever
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.pinecone import PineconeVectorStore
from pinecone import Pinecone
from pydantic import BaseModel, ConfigDict

from rag.upsert import PAGE_UNKNOWN_SENTINEL

NAMESPACES: tuple[str, ...] = ("tfl_business_plan", "mts_2018", "tfl_annual_report")
DEFAULT_TOP_K = 5


class TflDocSnippet(BaseModel):
    """Flat retrieval hit returned to the agent."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    doc_title: str
    section_title: str
    page_start: int | None
    page_end: int | None
    text: str
    score: float
    resolved_url: str


def build_retriever(
    *,
    pinecone_api_key: str,
    openai_api_key: str,
    index_name: str,
) -> dict[str, BaseRetriever]:
    """Build one LlamaIndex retriever per Pinecone namespace.

    Args:
        pinecone_api_key: Pinecone API key.
        openai_api_key: OpenAI API key (for the embedding model).
        index_name: Pinecone index name (e.g. ``"tfl-strategy-docs"``).

    Returns:
        Dict mapping namespace (``doc_id``) to its retriever.
    """
    pc = Pinecone(api_key=pinecone_api_key)
    pinecone_index = pc.Index(index_name)
    embed_model = OpenAIEmbedding(
        model="text-embedding-3-small",
        api_key=openai_api_key,
    )
    return {
        ns: VectorStoreIndex.from_vector_store(
            PineconeVectorStore(pinecone_index=pinecone_index, namespace=ns),
            embed_model=embed_model,
        ).as_retriever(similarity_top_k=DEFAULT_TOP_K)
        for ns in NAMESPACES
    }


async def retrieve(
    retrievers: dict[str, BaseRetriever],
    *,
    query: str,
    doc_id: str | None,
    top_k: int,
) -> list[TflDocSnippet]:
    """Retrieve top-``k`` snippets, fanning out across namespaces if needed.

    Args:
        retrievers: Namespace → retriever map from ``build_retriever``.
        query: Natural-language search query.
        doc_id: Restrict search to one namespace. ``None`` fans out
            across every namespace in ``retrievers``.
        top_k: Maximum number of snippets to return.

    Returns:
        Snippets sorted by score descending and capped at ``top_k``.
    """
    targets = [doc_id] if doc_id is not None else list(retrievers.keys())
    coros = [_one(retrievers[ns], query) for ns in targets if ns in retrievers]
    nested = await asyncio.gather(*coros)
    flat = [hit for hits in nested for hit in hits]
    flat.sort(key=lambda h: h.score, reverse=True)
    return flat[:top_k]


async def _one(retriever: BaseRetriever, query: str) -> list[TflDocSnippet]:
    nodes = await retriever.aretrieve(query)
    return [_to_snippet(node) for node in nodes]


def _normalise_page(value: Any) -> int | None:
    """Map the TM-D4 ``-1`` page sentinel (and ``None``) to ``None``."""
    if value is None or value == PAGE_UNKNOWN_SENTINEL:
        return None
    return int(value)


def _to_snippet(node: Any) -> TflDocSnippet:
    """Coerce a LlamaIndex ``NodeWithScore`` into ``TflDocSnippet``.

    Reads metadata laid down by ``rag.upsert.upsert_chunks``; maps the
    page sentinel back to ``None``.
    """
    meta_source = getattr(node, "metadata", None)
    if not meta_source:
        inner = getattr(node, "node", None)
        meta_source = getattr(inner, "metadata", None) if inner is not None else None
    meta: dict[str, Any] = dict(meta_source or {})

    page_start = meta.get("page_start")
    page_end = meta.get("page_end")

    text = meta.get("text") or getattr(node, "text", None)
    if not text:
        inner = getattr(node, "node", None)
        text = getattr(inner, "text", "") if inner is not None else ""

    raw_score = getattr(node, "score", None)
    score = float(raw_score) if raw_score is not None else 0.0

    return TflDocSnippet(
        doc_id=str(meta.get("doc_id", "")),
        doc_title=str(meta.get("doc_title", "")),
        section_title=str(meta.get("section_title", "")),
        page_start=_normalise_page(page_start),
        page_end=_normalise_page(page_end),
        text=str(text or ""),
        score=score,
        resolved_url=str(meta.get("resolved_url", "")),
    )
